import gc
from time import sleep
import os

from llama_hub.confluence.base import ConfluenceReader
from loguru import logger
from slack_bolt.adapter.socket_mode import SocketModeHandler

from builders import build_write_index, build_read_index, reset, build_service_context
from slack_bolt import App
from dotenv import load_dotenv

def load_confluence_data(include_attachments=False):
    space_keys = ["CAP", "RA", "TRAIN", "AL"]
    base_url = "https://capspire.atlassian.net/wiki"
    reader = ConfluenceReader(base_url=base_url)
    logger.info("loading space page")
    documents = []
    for key in space_keys:
        logger.info(f"loading space {key}")
        new_documents = reader.load_data(
            space_key=key,
            include_attachments=include_attachments,
            page_status="current",
        )
        logger.info(f"loaded {len(new_documents)} documents")
        documents.extend(new_documents)
    logger.info("building index")
    build_write_index(documents)

if __name__ == "__main__":
    load_dotenv()
    assert os.getenv("SLACK_BOT_TOKEN"), "SLACK_BOT_TOKEN not set in environment"
    load_confluence_data()
