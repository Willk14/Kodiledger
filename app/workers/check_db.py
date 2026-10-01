import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


async def main():
    print("SYSTEM_DATABASE_URL:", settings.SYSTEM_DATABASE_URL)

    engine = create_async_engine(
        settings.SYSTEM_DATABASE_URL,
        echo=False,
    )

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT
                    current_database(),
                    current_user,
                    current_schema(),
                    inet_server_addr(),
                    inet_server_port()
                """
            )
        )

        print("PYTEST DB IDENTITY:", result.fetchone())

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

    