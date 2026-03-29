from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from software_factory.api.routes.config_route import router as config_router
from software_factory.api.routes.factory import router as factory_router
from software_factory.api.routes.projects import router as projects_router
from software_factory.api.routes.skills import router as skills_router
from software_factory.config.settings import get_settings
from software_factory.db.config_service import load_runtime_config, seed_from_yaml
from software_factory.db.database import create_tables, get_session, init_engine
from software_factory.db.seeds import seed_default_skills

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AI Software Factory",
        description="根据自然语言需求描述，自动化完成软件开发全流程",
        version="0.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API 路由
    app.include_router(factory_router)
    app.include_router(projects_router)
    app.include_router(config_router)
    app.include_router(skills_router)

    # 前端静态文件
    frontend_dir = Path(__file__).parent.parent.parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    else:
        logger.warning("Frontend directory not found at %s", frontend_dir)

    @app.on_event("startup")
    async def startup():
        logger.info("AI Software Factory v2 starting on %s:%s", settings.host, settings.port)
        # 初始化数据库
        try:
            init_engine(settings.database_url)
            await create_tables()
            async with get_session() as session:
                seeded = await seed_default_skills(session)
                if seeded:
                    logger.info("Seeded %d default skills", seeded)
            async with get_session() as session:
                cfg_seeded = await seed_from_yaml(session, settings.config_yaml_path)
                if cfg_seeded:
                    logger.info("Config seeded from config.yaml into database")
            async with get_session() as session:
                await load_runtime_config(session)
                logger.info("Runtime config loaded from database")
            logger.info("Database ready")
        except Exception as e:
            logger.error("Database initialization failed: %s", e)
            logger.warning("App will start but database features may not work")

    return app


app = create_app()


def main():
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "software_factory.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
