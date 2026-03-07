#!/usr/bin/env python3
"""Process PDF documents using Microsoft Azure Document Intelligence."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import get_logger

log = get_logger("process_pdf")

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Process a PDF document using Azure Document Intelligence"
    )
    parser.add_argument(
        "source_pdf",
        type=str,
        help="Path to the source PDF file to process",
    )
    return parser.parse_args()


def main():
    """Main function to process PDF document."""
    args = parse_args()

    # Load environment variables
    load_dotenv()

    api_key = os.getenv("AZURE_DI_KEY")
    endpoint = os.getenv("AZURE_DI_ENDPOINT")

    if not api_key or not endpoint:
        log.error("AZURE_DI_KEY and AZURE_DI_ENDPOINT must be set in .env file")
        sys.exit(1)

    # Validate source file exists
    source_path = Path(args.source_pdf)
    if not source_path.exists():
        log.error("Source file not found: %s", args.source_pdf)
        sys.exit(1)

    if not source_path.suffix.lower() == ".pdf":
        log.warning("File does not have .pdf extension: %s", args.source_pdf)

    # Create output filename
    output_path = source_path.with_suffix(".json")

    log.info("Processing: %s", source_path)
    log.info("Output will be saved to: %s", output_path)

    # Initialize the Document Intelligence client
    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(api_key),
        api_version='2024-11-30'
    )

    # Read the PDF file
    with open(source_path, "rb") as pdf_file:
        pdf_bytes = pdf_file.read()

    # Analyze the document with markdown output format
    log.info("Uploading and analyzing document...")
    poller = client.begin_analyze_document(
        model_id="prebuilt-layout",
        pages=None,
        body=AnalyzeDocumentRequest(bytes_source=pdf_bytes),
        #body=pdf_bytes,
        #content_type='application/octet-stream',
        output_content_format=DocumentContentFormat.MARKDOWN,
    )

    # Wait for the result
    result = poller.result()

    # Convert result to dictionary
    result_dict = result.as_dict()

    # Save the full JSON response
    with open(output_path, "w", encoding="utf-8") as json_file:
        json.dump(result_dict, json_file, indent=2, ensure_ascii=False)

    log.info("Analysis complete. Results saved to: %s", output_path)
    log.info("Content format: markdown")
    log.info("Pages analyzed: %d", len(result_dict.get('pages', [])))


if __name__ == "__main__":
    main()
