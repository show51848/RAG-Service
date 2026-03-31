"""
Root test configuration.

這個 conftest.py 必須在 os.environ 設定後，app 模組才被 import。
pytest 保證 conftest.py 先於 test_*.py 載入，所以在此處設定環境變數
可以確保 Settings() 實例化時看得到這些值。

原因：config.py 的 SECRET_KEY 和 ANTHROPIC_API_KEY 已移除預設值，
啟動時若未設定就會 fail-fast。測試環境不需要真實的 key（LLM 呼叫全部被
mock 掉），但 pydantic 的 validator 仍然需要值存在且格式合法。
"""
import os

# 在任何 app 模組被 import 之前設定測試用環境變數
# setdefault 確保若使用者已在 shell 設定了真實 key，不會被覆蓋
os.environ.setdefault("SECRET_KEY", "pytest-secret-key-for-testing-only-min32!!")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real-just-for-pytest")
os.environ.setdefault("APP_ENV", "development")
