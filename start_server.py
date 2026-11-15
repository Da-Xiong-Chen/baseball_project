"""啟動本機完整版（2026 球季批次）：python start_server.py 後開啟 http://127.0.0.1:8000

與 GitHub Pages 網站使用同一個批次：2026 球季名單與背號、模型以 2024–2026 訓練。
需先執行 python download_data.py 取得 2024–2026 原始資料與 2026 守位檔。
已設定的 BASEBALL_* 環境變數優先；直接執行 python server.py 則是原 v5（2024–2025）批次。
"""
import os
import runpy

ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault('BASEBALL_RUNTIME_CONFIG', os.path.join(ROOT, 'config', 'site-2026.json'))
os.environ.setdefault('BASEBALL_MODEL_DIR', os.path.join(ROOT, 'models', '2026'))
os.environ.setdefault('BASEBALL_BATCH_CONTEXT', os.path.join(ROOT, 'models', '2026', 'batch-context.json'))

if __name__ == '__main__':
    runpy.run_path(os.path.join(ROOT, 'server.py'), run_name='__main__')
