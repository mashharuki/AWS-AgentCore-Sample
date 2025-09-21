#!/usr/bin/env python3
"""AWS Cost Estimation Agentのシンプルなテストコード"""

import argparse  # コマンドライン引数を解析するためのモジュール
import asyncio  # 非同期処理のためのモジュール

from cost_estimator_agent.cost_estimator_agent import \
    AWSCostEstimatorAgent  # AWSコスト見積もりエージェントをインポート


async def test_streaming(architecture: str, verbose: bool = True):
    """
    ストリーミング形式でのコスト見積もりをテストする関数。
    Strandsのベストプラクティスに従っているか確認します。
    """
    if verbose:
        print("\n🔄 ストリーミングでのコスト見積もりをテスト中...")
    # エージェントのインスタンスを作成
    agent = AWSCostEstimatorAgent()
    
    # 引数で提供されたアーキテクチャ記述を使用、またはデフォルト値を使用
    
    try:
        total_chunks = 0
        total_length = 0
        
        # エージェントからのストリーミングイベントを非同期でループ処理
        async for event in agent.estimate_costs_stream(architecture):
            if "data" in event:
                # Strandsのドキュメントによると、event["data"]には新しい差分コンテンツのみが含まれる
                # そのため、そのまま出力できる
                chunk_data = str(event["data"])
                if verbose:
                    print(chunk_data, end="", flush=True)
                
                # デバッグ用にチャンク数と総文字数を追跡
                total_chunks += 1
                total_length += len(chunk_data)
                
            elif "error" in event:
                if verbose:
                    print(f"\n❌ ストリーミングエラー: {event['data']}")
                return False
        
        if verbose:
            print(f"\n📊 ストリーミング完了: {total_chunks}個のチャンク、合計{total_length}文字")
        # 0文字より多ければ成功とみなす
        return total_length > 0
        
    except Exception as e:
        if verbose:
            print(f"❌ ストリーミングテスト失敗: {e}")
        return False

def test_regular(architecture: str = "One EC2 t3.micro instance running 24/7", verbose: bool = True):
    """
    通常の（非ストリーミング）コスト見積もりをテストする関数。
    """
    if verbose:
        print("📄 通常のコスト見積もりをテスト中...")
    agent = AWSCostEstimatorAgent()
    
    # 引数で提供されたアーキテクチャ記述を使用、またはデフォルト値を使用
    
    try:
        # コスト見積もり結果を一度に取得
        result = agent.estimate_costs(architecture)
        if verbose:
            print(f"📊 通常のレスポンスの長さ: {len(result)} 文字")
            print(f"結果のプレビュー: {result[:150]}...")
        # 結果の文字数が0より多ければ成功とみなす
        return len(result) > 0
    except Exception as e:
        if verbose:
            print(f"❌ 通常テスト失敗: {e}")
        return False

def parse_arguments():
    """コマンドライン引数を解析する関数"""
    parser = argparse.ArgumentParser(description='AWS Cost Estimation Agentのテスト')
    
    parser.add_argument(
        '--architecture', 
        type=str, 
        default="One EC2 t3.micro instance running 24/7",
        help='テストするアーキテクチャの説明文 (デフォルト: "One EC2 t3.micro instance running 24/7")'
    )
    
    parser.add_argument(
        '--tests',
        nargs='+', # 1つ以上の引数を受け付ける
        choices=['regular', 'streaming', 'debug'],
        default=['regular'],
        help='実行するテストの種類 (デフォルト: regular)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true', # このフラグが存在すればTrue
        default=True,
        help='詳細な出力を有効にする (デフォルト: True)'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true', # このフラグが存在すればTrue
        help='詳細な出力を無効にする'
    )
    
    return parser.parse_args()

async def main():
    """
    プログラムのメイン処理を定義する非同期関数。
    引数を解析し、選択されたテストを実行します。
    """
    args = parse_arguments()
    
    # --verboseと--quietフラグを組み合わせて、最終的なverbose設定を決定
    verbose = args.verbose and not args.quiet
    
    print("🚀 AWSコストエージェントのテストを開始します")
    if verbose:
        print(f"アーキテクチャ: {args.architecture}")
        print(f"実行するテスト: {', '.join(args.tests)}")
    
    results = {}
    
    # 選択されたテストを実行
    if 'regular' in args.tests:
        results['regular'] = test_regular(args.architecture, verbose)
    
    if 'streaming' in args.tests:
        results['streaming'] = await test_streaming(args.architecture, verbose)
    
    # テスト結果を出力
    if verbose:
        print("\n📋 テスト結果:")
        for test_name, success in results.items():
            status = '✅ PASS' if success else '❌ FAIL'
            print(f"   {test_name.capitalize()}の実装: {status}")
        
        if all(results.values()): # すべてのテストが成功したか確認
            print("🎉 すべてのテストが正常に完了しました！")
        else:
            print("⚠️ いくつかのテストが失敗しました - 上記のログを確認してください")
    
    # 結果に基づいて終了コードを返す
    # すべて成功した場合は0、そうでなければ1
    return 0 if all(results.values()) else 1

if __name__ == "__main__":
    import sys

    # main関数を非同期で実行し、終了コードを取得
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
    # main関数を非同期で実行し、終了コードを取得
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
    # main関数を非同期で実行し、終了コードを取得
    exit_code = asyncio.run(main())
    sys.exit(exit_code)