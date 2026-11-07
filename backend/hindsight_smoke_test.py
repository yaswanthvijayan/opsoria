import os
import sys
from dotenv import load_dotenv
from hindsight_client import Hindsight


def main():
    # 1. Load environment variables
    load_dotenv()
    api_key = os.getenv("HINDSIGHT_API_KEY")
    base_url = os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io")
    bank_id = os.getenv("HINDSIGHT_BANK_ID", "opsoria-incidents")

    if not api_key:
        print("ERROR: HINDSIGHT_API_KEY is not set or empty in .env.")
        sys.exit(1)

    print(f"Hindsight base URL: {base_url}")
    print(f"Target memory bank: {bank_id}")
    print("API Key loaded: [PRESENT, NOT DISPLAYED]")

    client = None
    try:
        # 2. Initialize Hindsight client
        client = Hindsight(
            base_url=base_url,
            api_key=api_key,
            timeout=90.0,
        )
        print("Hindsight client initialized successfully.")

        # 3. Retain: Exactly ONE synthetic test incident
        print("\n--- STEP A: RETAIN ---")
        synthetic_content = (
            "[STATUS: UNVERIFIED TEST DATA]\n"
            "Incident ID: OPSORIA-TEST-001\n"
            "Service: synthetic payment-service\n"
            "Environment: synthetic staging environment\n"
            "Symptom: HTTP 503 errors after a deployment\n"
            "Possible Cause: Incompatible configuration introduced during deployment (Unconfirmed)\n"
            "Resolution: Not yet confirmed\n"
            "Notes: This is synthetic test data for Opsoria smoke testing only."
        )

        print("Starting Retain...", flush=True)

        retain_response = client.retain(
            bank_id=bank_id,
            content=synthetic_content,
            document_id="OPSORIA-TEST-001",
            metadata={"incident_id": "OPSORIA-TEST-001", "type": "synthetic_test"},
            tags=["test", "synthetic", "payment-service"],
        )

        print("Retain completed.", flush=True)
        print(f"Retain success: {getattr(retain_response, 'success', True)}")
        print(f"Items count: {getattr(retain_response, 'items_count', 'N/A')}")
        if hasattr(retain_response, "usage") and retain_response.usage:
            print(f"Usage / Credit info reported: {retain_response.usage}")
        else:
            print("Usage / Credit info reported: None")

        # 4. Recall: Exactly ONE natural-language recall query
        print("\n--- STEP B: RECALL ---")
        recall_query = "Find the previous synthetic payment-service incident involving HTTP 503 errors after deployment."
        print(f"Query: {recall_query}")
        print("Starting Recall...", flush=True)

        recall_response = client.recall(
            bank_id=bank_id,
            query=recall_query,
        )

        print("Recall completed.", flush=True)
        results = getattr(recall_response, "results", []) or []
        print(f"Retrieved items count: {len(results)}")

        test_record_found = False
        for idx, res in enumerate(results, 1):
            text = getattr(res, "text", "")
            doc_id = getattr(res, "document_id", "")
            metadata = getattr(res, "metadata", {}) or {}

            print(f"\nResult #{idx}:")
            print(f"  Document ID: {doc_id}")
            print(f"  Type: {getattr(res, 'type', 'N/A')}")
            print(f"  Scores: {getattr(res, 'scores', 'N/A')}")
            print(f"  Text: {text}")

            if (
                "OPSORIA-TEST-001" in text
                or doc_id == "OPSORIA-TEST-001"
                or (metadata and metadata.get("incident_id") == "OPSORIA-TEST-001")
            ):
                test_record_found = True

        print("\n--- SUMMARY ---")
        print(f"OPSORIA-TEST-001 retrieved: {test_record_found}")

    except Exception as e:
        err_msg = str(e)
        if api_key:
            err_msg = err_msg.replace(api_key, "[REDACTED]")
        print(f"\nERROR ENCOUNTERED: {type(e).__name__}: {err_msg}")
        sys.exit(1)
    finally:
        if client:
            try:
                client.close()
                print("Client closed successfully.")
            except Exception as close_err:
                print(f"Error closing client: {close_err}")


if __name__ == "__main__":
    main()
