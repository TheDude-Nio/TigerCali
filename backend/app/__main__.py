"""python -m app  启动服务（生产环境也可以直接用 uvicorn app.main:app）。"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("TIGERCALI_HOST", "0.0.0.0"),
        port=int(os.environ.get("TIGERCALI_PORT", "8000")),
        workers=int(os.environ.get("TIGERCALI_WORKERS", "1")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
