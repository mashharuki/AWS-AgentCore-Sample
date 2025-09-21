import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from cost_estimator_agent.cost_estimator_agent import AWSCostEstimatorAgent
from bedrock_agentcore.runtime import BedrockAgentCoreApp

# AgentCoreアプリケーションの初期化
app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload):
    # プロンプトを取得
    user_input = payload.get("prompt")
    # コスト見積もりエージェントのインスタンス化
    agent = AWSCostEstimatorAgent()

    # バッチ処理の実行
    return agent.estimate_costs(user_input)


if __name__ == "__main__":
    app.run()
