"""
AWS Cost Estimation Agent（Amazon Bedrock AgentCore Code Interpreterを利用）

このエージェントは、以下の機能を実現します。
1. **AWS Pricing MCP Server** を使用して、最新のAWS料金データを取得
2. **AgentCore Code Interpreter** を利用して、安全な環境でコスト計算を実行
3. AWSアーキテクチャに対する包括的なコスト見積もりを提供

主な特徴:
- AgentCoreのサンドボックス内での安全なコード実行
- AWSのリアルタイム料金データへのアクセス
- 包括的なログ出力とエラーハンドリング
- 段階的に複雑な処理を構築
"""

import logging  # ログ出力のためのモジュール
import traceback  # エラーのスタックトレースを取得するためのモジュール
from contextlib import contextmanager  # コンテキストマネージャを定義するためのデコレータ
from typing import AsyncGenerator, Generator  # 型ヒントのためのモジュール

import boto3  # AWS SDK for Python (Boto3)
from bedrock_agentcore.tools.code_interpreter_client import \
    CodeInterpreter  # AgentCore Code Interpreterクライアント
from botocore.config import Config  # Boto3の設定
from cost_estimator_agent.config import (  # 設定ファイルをインポート
    COST_ESTIMATION_PROMPT, DEFAULT_MODEL, LOG_FORMAT, SYSTEM_PROMPT)
from mcp import (StdioServerParameters,  # MCP (Multi-Client Protocol)のためのモジュール
                 stdio_client)
from strands import Agent, tool  # Strandsエージェントフレームワークの主要コンポーネント
from strands.handlers.callback_handler import \
    null_callback_handler  # コールバックハンドラ
from strands.models import BedrockModel  # Bedrockモデル
from strands.tools.mcp import MCPClient  # MCPクライアント

# デバッグや監視のために包括的なログを設定
logging.basicConfig(
    level=logging.ERROR,  # デフォルトはエラーのみ、詳細なデバッグにはDEBUGに変更可能
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler()]
)

# Strandsのデバッグログを詳細に出力
logging.getLogger("strands").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


class AWSCostEstimatorAgent:
    """
    AgentCore Code Interpreterを利用したAWSコスト見積もりエージェント
    
    以下の要素を組み合わせています:
    - MCP料金ツール（自動的に利用可能）: リアルタイムな料金データを提供
    - AgentCore Code Interpreter: 安全な計算実行環境を提供
    - Strands Agentsフレームワーク: クリーンな実装を実現
    """
    
    def __init__(self, region: str = ""):
        """
        コスト見積もりエージェントの初期化
        
        Args:
            region: AgentCore Code Interpreterが動作するAWSリージョン
        """
        self.region = region
        if not self.region:
            # リージョンが指定されていなければ、Boto3セッションのデフォルトリージョンを使用
            self.region = boto3.Session().region_name
        self.code_interpreter = None # Code Interpreterクライアント
        
        logger.info(f"AWS Cost Estimator Agentをリージョン: {self.region} で初期化中")
        
    def _setup_code_interpreter(self) -> None:
        """AgentCore Code Interpreterをセットアップし、安全な計算環境を準備する"""
        try:
            logger.info("AgentCore Code Interpreterをセットアップ中...")
            # Code Interpreterクライアントを初期化
            self.code_interpreter = CodeInterpreter(self.region)
            self.code_interpreter.start() # Code Interpreterセッションを開始
            logger.info("✅ AgentCore Code Interpreterセッションが正常に開始されました")
        except Exception as e:
            logger.error(f"❌ Code Interpreterのセットアップに失敗しました: {e}")
            return  # エラーを再発生させず、エラーハンドリングを継続

    def _get_aws_credentials(self) -> dict:
        """
        現在のAWS認証情報（セッショントークンを含む）を取得する
        
        Returns:
            現在のAWS認証情報を含む辞書
        """
        try:
            logger.info("現在のAWS認証情報を取得中...")
            
            # 現在の認証情報を取得するためにセッションを作成
            session = boto3.Session()
            credentials = session.get_credentials()
            
            if credentials is None:
                raise Exception("AWS認証情報が見つかりません")
            
            # 認証情報が有効か確認するために、STSクライアントでCaller Identityを取得
            sts_client = boto3.client('sts', region_name=self.region)
            identity = sts_client.get_caller_identity()
            logger.info(f"使用中のAWS ID: {identity.get('Arn', '不明')}")
            
            # 認証情報を凍結してアクセスしやすくする
            frozen_creds = credentials.get_frozen_credentials()
            
            credential_dict = {
                "AWS_ACCESS_KEY_ID": frozen_creds.access_key,
                "AWS_SECRET_ACCESS_KEY": frozen_creds.secret_key,
                "AWS_REGION": self.region
            }
            
            # セッショントークンがあれば追加（EC2インスタンスロールなどが提供）
            if frozen_creds.token:
                credential_dict["AWS_SESSION_TOKEN"] = frozen_creds.token
                logger.info("✅ セッショントークン付きのAWS認証情報を使用中（EC2インスタンスロールの可能性が高い）")
            else:
                logger.info("✅ セッショントークンなしのAWS認証情報を使用中")
                
            return credential_dict
            
        except Exception as e:
            logger.error(f"❌ AWS認証情報の取得に失敗しました: {e}")
            return {}  # フォールバックとして空の辞書を返す

    def _setup_aws_pricing_client(self) -> MCPClient:
        """現在のAWS認証情報を使用してAWS Pricing MCPクライアントをセットアップする"""
        try:
            logger.info("AWS Pricing MCPクライアントをセットアップ中...")
            
            # 現在の認証情報（セッショントークンを含む）を取得
            aws_credentials = self._get_aws_credentials()
            
            # MCPクライアント用の環境変数を準備
            env_vars = {
                "FASTMCP_LOG_LEVEL": "ERROR",
                **aws_credentials  # すべてのAWS認証情報を含める
            }
            
            # MCPクライアントを作成
            aws_pricing_client = MCPClient(
                lambda: stdio_client(StdioServerParameters(
                    command="uvx", # Python仮想環境でコマンドを実行するツール
                    args=["awslabs.aws-pricing-mcp-server@latest"],
                    env=env_vars
                ))
            )
            logger.info("✅ AWS Pricing MCPクライアントがAWS認証情報で正常にセットアップされました")
            return aws_pricing_client
        except Exception as e:
            logger.error(f"❌ AWS Pricing MCPクライアントのセットアップに失敗しました: {e}")
            return None  # フォールバックとしてNoneを返す
    
    
    @tool # Strandsのツールとして登録
    def execute_cost_calculation(self, calculation_code: str, description: str = "") -> str:
        """
        AgentCore Code Interpreterを使用してコスト計算を実行する
        
        Args:
            calculation_code: コスト計算のためのPythonコード
            description: 計算内容の説明
            
        Returns:
            計算結果の文字列
        """
        if not self.code_interpreter:
            return "❌ Code Interpreterが初期化されていません"
            
        try:
            logger.info(f"🧮 計算を実行中: {description}")
            logger.debug(f"実行するコード:\n{calculation_code}")
            
            # 安全なAgentCoreサンドボックス内でコードを実行
            response = self.code_interpreter.invoke("executeCode", {
                "language": "python",
                "code": calculation_code
            })
            
            # レスポンスストリームから結果を抽出
            results = []
            for event in response.get("stream", []):
                if "result" in event:
                    result = event["result"]
                    if "content" in result:
                        for content_item in result["content"]:
                            if content_item.get("type") == "text":
                                results.append(content_item["text"])
            
            result_text = "\n".join(results)
            logger.info("✅ 計算が正常に完了しました")
            logger.debug(f"計算結果: {result_text}")
            
            return result_text
            
        except Exception as e:
            logger.exception(f"❌ 計算に失敗しました: {e}")

    @contextmanager
    def _estimation_agent(self) -> Generator[Agent, None, None]:
        """
        コスト見積もりコンポーネントのためのコンテキストマネージャ
        
        Yields:
            すべてのツールが設定され、リソースが適切に管理されたAgentオブジェクト
            
        保証:
            Code InterpreterとMCPクライアントのリソースが適切にクリーンアップされる
        """        
        try:
            logger.info("🚀 AWS Cost Estimation Agentを初期化中...")
            
            # コンポーネントを順番にセットアップ
            self._setup_code_interpreter()
            aws_pricing_client = self._setup_aws_pricing_client()
            
            # MCPコンテキストを維持したままエージェントを作成
            with aws_pricing_client:
                pricing_tools = aws_pricing_client.list_tools_sync()
                logger.info(f"{len(pricing_tools)}個のAWS料金ツールが見つかりました")
                
                # execute_cost_calculationとMCP料金ツールの両方でエージェントを作成
                # 呼び出すツールを設定する
                all_tools = [self.execute_cost_calculation] + pricing_tools
                # Bedrockモデルを使用してエージェントを初期化
                agent = Agent(
                    BedrockModel(
                        boto_client_config=Config(
                            read_timeout=900,
                            connect_timeout=900,
                            retries=dict(max_attempts=3, mode="adaptive"),
                        ),
                        model_id=DEFAULT_MODEL
                    ),
                    tools=all_tools,
                    system_prompt=SYSTEM_PROMPT
                )
                
                yield agent # エージェントオブジェクトを呼び出し元に提供
                
        except Exception as e:
            logger.exception(f"❌ コンポーネントのセットアップに失敗しました: {e}")
            raise # 例外を再発生させる
        finally:
            # 成功/失敗にかかわらず、必ずクリーンアップが実行されるようにする
            self.cleanup()

    def estimate_costs(self, architecture_description: str) -> str:
        """
        指定されたアーキテクチャ記述のコストを見積もる
        
        Args:
            architecture_description: 見積もり対象のシステムの記述
            
        Returns:
            連結されたコスト見積もり結果の文字列
        """
        logger.info("📊 コスト見積もりを開始します...")
        logger.info(f"アーキテクチャ: {architecture_description}")
        
        try:
            with self._estimation_agent() as agent:
                # エージェントを使用してコスト見積もりリクエストを処理
                prompt = COST_ESTIMATION_PROMPT.format(
                    architecture_description=architecture_description
                )
                result = agent(prompt)
                
                logger.info("✅ コスト見積もりが完了しました")

                if result.message and result.message.get("content"):
                    # すべてのContentBlockからテキストを抽出し、連結
                    text_parts = []
                    for content_block in result.message["content"]:
                        if isinstance(content_block, dict) and "text" in content_block:
                            text_parts.append(content_block["text"])
                    return "".join(text_parts) if text_parts else "テキストコンテンツが見つかりませんでした。"
                else:
                    return "見積もり結果がありません。"

        except Exception as e:
            logger.exception(f"❌ コスト見積もりに失敗しました: {e}")
            error_details = traceback.format_exc()
            return f"❌ コスト見積もりに失敗しました: {e}\n\nスタックトレース:\n{error_details}"

    async def estimate_costs_stream(self, architecture_description: str) -> AsyncGenerator[dict, None]:
        """
        ストリーミングレスポンスでコスト見積もりを実行する
        
        Amazon Bedrockのベストプラクティスに従い、適切なデルタベースのストリーミングを実装。
        これにより、Strandsのstream_async()が重複したコンテンツチャンクを送信する一般的な問題を解決します。
        
        Args:
            architecture_description: 見積もり対象のシステムの記述
            
        Yields:
            真のデルタコンテンツ（新規テキストのみ、重複なし）を含むストリーミングイベント
            
        使用例:
            async for event in agent.estimate_costs_stream(description):
                if "data" in event:
                    print(event["data"], end="", flush=True)  # 直接出力、蓄積不要
        """
        logger.info("📊 ストリーミングコスト見積もりを開始します...")
        logger.info(f"アーキテクチャ: {architecture_description}")
        
        try:
            with self._estimation_agent() as agent:
                # ストリーミングでコスト見積もりリクエストを処理
                prompt = COST_ESTIMATION_PROMPT.format(
                    architecture_description=architecture_description
                )
                
                logger.info("🔄 ストリーミングコスト見積もりレスポンスを処理中...")
                
                # 重複を防ぐための適切なデルタハンドリングを実装
                # これはAmazon BedrockのContentBlockDeltaEventパターンに従う
                previous_output = ""
                # 呼び出す
                agent_stream = agent.stream_async(prompt, callback_handler=null_callback_handler)
                
                async for event in agent_stream:
                    if "data" in event:
                        current_chunk = str(event["data"])
                        
                        # Bedrockのベストプラクティスに従い、デルタを計算
                        if current_chunk.startswith(previous_output):
                            # これは増分更新 - 新しい部分のみを抽出
                            delta_content = current_chunk[len(previous_output):]
                            if delta_content:  # 実際に新しいコンテンツがあれば出力
                                previous_output = current_chunk
                                yield {"data": delta_content}
                        else:
                            # これは完全に新しいチャンクかリセット - そのまま出力
                            previous_output = current_chunk
                            yield {"data": current_chunk}
                    else:
                        # データ以外のイベント（エラー、メタデータなど）はそのまま通過
                        yield event
                
                logger.info("✅ ストリーミングコスト見積もりが完了しました")

        except Exception as e:
            logger.exception(f"❌ ストリーミングコスト見積もりに失敗しました: {e}")
            # ストリーミング形式でエラーイベントをyield
            yield {
                "error": True,
                "data": f"❌ ストリーミングコスト見積もりに失敗しました: {e}\n\nスタックトレース:\n{traceback.format_exc()}"
            }

    def cleanup(self) -> None:
        """リソースをクリーンアップする関数"""
        logger.info("🧹 リソースをクリーンアップ中...")
        
        if self.code_interpreter:
            try:
                self.code_interpreter.stop() # Code Interpreterセッションを停止
                logger.info("✅ Code Interpreterセッションが停止しました")
            except Exception as e:
                logger.warning(f"⚠️ Code Interpreterの停止中にエラーが発生しました: {e}")
            finally:
                self.code_interpreter = None                logger.warning(f"⚠️ Code Interpreterの停止中にエラーが発生しました: {e}")
            finally:
                self.code_interpreter = None                logger.warning(f"⚠️ Code Interpreterの停止中にエラーが発生しました: {e}")
            finally:
                self.code_interpreter = None