import asyncio

from app.core.config import PublisherSettings


async def run_forever(settings: PublisherSettings) -> None:
    """TODO: publisher loop on queue "publisher".

    Job kinds: "publish" (app/publisher/postgres.py) and "metabase_sync"
    (app/metabase/builder.py). Refuse any job whose approval fingerprint does
    not match the current version.
    """
    raise NotImplementedError


def main() -> None:
    asyncio.run(run_forever(PublisherSettings()))


if __name__ == "__main__":
    main()
