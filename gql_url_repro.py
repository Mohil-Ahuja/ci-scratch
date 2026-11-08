# Repro: the gql integration sends the GraphQL transport URL, credentials included, as event.request.url.
import re
import sentry_sdk
from sentry_sdk.integrations.gql import GQLIntegration
from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport
import responses

events = []
sentry_sdk.init(
    dsn="https://public@example.invalid/1",
    integrations=[GQLIntegration()],
    send_default_pii=False,
    before_send=lambda e, h: events.append(e) or None,
)

url = "https://deploy-bot:s3cr3t@api.example.com/graphql?access_token=tok_live_123"
with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
    rsps.post(re.compile(r"https://.*api\.example\.com/graphql.*"), json={"errors": [{"message": "boom"}]})
    client = Client(transport=RequestsHTTPTransport(url=url))
    try:
        client.execute(gql("{ me { id } }"))
    except Exception as e:
        print('caught:', type(e).__name__, e)
        sentry_sdk.capture_exception()

sentry_sdk.flush()
print(events[0]["request"]["url"])
# Expected (same as the requests/httpx breadcrumbs): https://[Filtered]:[Filtered]@api.example.com/graphql
# Actual:   https://deploy-bot:s3cr3t@api.example.com/graphql?access_token=tok_live_123
print("send_default_pii=False")
print("request:", events[0]["request"])
print("http breadcrumbs:", [b.get("data", {}).get("url") for b in events[0].get("breadcrumbs", {}).get("values", []) if b.get("type") == "http"])
from sentry_sdk.utils import parse_url
print("parse_url:", parse_url(url, sanitize=False))
u = events[0]["request"]["url"]
print("username in event url:", "deploy-bot" in u)
print("password in event url:", "s3cr3t" in u)
print("token in event url:", "tok_live_123" in u)
print("url with colon-at spaced:", u.replace("://", ":// ").replace(":s3", " : s3").replace("@", " @ "))
print("event count:", len(events), "| exception type:", events[0]["exception"]["values"][-1]["type"])
