"""Probe the Doubleword Batch API to discover available batch data.

Lists all batches on the account and dumps their full structure,
then attempts to match them to our known models.
"""

import asyncio
import json
from datetime import datetime, timezone

import llm_doubleword


async def main():
    client = llm_doubleword.create_client()

    # ── Try listing all batches ──────────────────────────────────
    print("=" * 70)
    print("Attempting client.batches.list(limit=100)...")
    print("=" * 70)
    try:
        batches = await client.batches.list(limit=100)
        batch_list = list(batches.data)
        print(f"Found {len(batch_list)} batch(es)\n")

        for batch in batch_list:
            raw = batch.model_dump() if hasattr(batch, "model_dump") else batch.__dict__
            print(f"--- Batch {batch.id} ---")
            print(json.dumps(raw, indent=2, default=str))
            print()

            # Summary line
            counts = batch.request_counts
            created = getattr(batch, "created_at", None)
            completed = getattr(batch, "completed_at", None)
            elapsed = None
            if created and completed:
                elapsed = completed - created
            print(f"  status={batch.status}  created={_ts(created)}  completed={_ts(completed)}  "
                  f"elapsed={elapsed}s  counts={counts}")
            print()

    except Exception as e:
        print(f"batches.list() failed: {type(e).__name__}: {e}")
        print("\nFalling back to retrieving the stale checkpoint batch...")
        await _probe_single(client, "1e0a6a49-f827-4742-9531-ca6c49e6d073")

    # ── Also probe the stale checkpoint entry ────────────────────
    checkpoint = llm_doubleword.load_checkpoint()
    for model_name, entry in checkpoint.items():
        print(f"\n{'=' * 70}")
        print(f"Checkpoint entry: {model_name}")
        print(f"{'=' * 70}")
        await _probe_single(client, entry["batch_id"])

    await client.close()


async def _probe_single(client, batch_id: str):
    """Retrieve and dump a single batch by ID."""
    try:
        batch = await client.batches.retrieve(batch_id)
        raw = batch.model_dump() if hasattr(batch, "model_dump") else batch.__dict__
        print(f"Batch {batch_id}:")
        print(json.dumps(raw, indent=2, default=str))

        created = getattr(batch, "created_at", None)
        completed = getattr(batch, "completed_at", None)
        elapsed = (completed - created) if created and completed else None
        counts = batch.request_counts
        print(f"\n  status={batch.status}  created={_ts(created)}  completed={_ts(completed)}  "
              f"elapsed={elapsed}s  counts={counts}")
    except Exception as e:
        print(f"Failed to retrieve batch {batch_id}: {type(e).__name__}: {e}")


def _ts(unix_ts):
    """Format unix timestamp to readable string, or 'N/A'."""
    if unix_ts is None:
        return "N/A"
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


if __name__ == "__main__":
    asyncio.run(main())
