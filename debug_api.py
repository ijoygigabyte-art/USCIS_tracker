"""Debug: fetch all 3 cases to see their data."""
import json
import requests
import config
import auth

cookies = auth.get_valid_cookies()

for receipt in config.RECEIPT_NUMBERS:
    url = f"{config.MYUSCIS_CASE_API}{receipt}"
    print(f"\n{'='*60}")
    print(f"Receipt: {receipt}")
    print(f"{'='*60}")
    resp = requests.get(url, cookies=cookies, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://my.uscis.gov/account/",
    })
    if resp.status_code == 200:
        data = resp.json()
        d = data.get("data", data)
        print(f"  Form: {d.get('formType', 'N/A')} - {d.get('formName', 'N/A')}")
        print(f"  Submitted: {d.get('submissionDate', 'N/A')}")
        print(f"  Last Updated: {d.get('updatedAt', 'N/A')} ({d.get('updatedAtTimestamp', 'N/A')})")
        print(f"  Closed: {d.get('closed', 'N/A')}")
        print(f"  Action Required: {d.get('actionRequired', 'N/A')}")
        print(f"  Premium: {d.get('isPremiumProcessed', 'N/A')}")
        print(f"  Channel: {d.get('elisChannelType', 'N/A')}")
        print(f"  Applicant: {d.get('applicantName', 'N/A')}")
        events = d.get("events", [])
        print(f"  Events ({len(events)}):")
        for e in events:
            print(f"    - [{e.get('eventCode')}] {e.get('eventDateTime')} (created: {e.get('createdAtTimestamp', 'N/A')[:19]})")
        notices = d.get("notices", [])
        print(f"  Notices: {len(notices)}")
        docs = d.get("documents", [])
        print(f"  Documents: {len(docs)}")
    else:
        print(f"  Error: HTTP {resp.status_code}")
