"""Live verification of financial metrics against real SEC EDGAR data."""

import asyncio
from quantix.config import Settings
from quantix.db import Database
from quantix.edgar.client import EdgarClient
from quantix.services.metrics import get_financials


async def main() -> None:
    settings = Settings(edgar_user_agent="QuantixResearch analyst@example.com")
    db = Database("test_verify.db")
    client = EdgarClient(settings=settings, db=db)

    companies = ["AAPL", "MSFT", "NVDA"]
    metrics = ["revenue", "net_income", "eps_diluted"]

    for ticker in companies:
        print(f"\n==================== Verifying {ticker} ====================")
        for m in metrics:
            res = await get_financials(client, ticker, m, periods=3, period_type="annual")
            status = res.get("status")
            tag = res.get("tag_used")
            unit = res.get("unit")
            print(f"{ticker} | {m} -> status: {status}, tag: {tag}, unit: {unit}")
            datapoints = res.get("datapoints", [])
            for dp in datapoints:
                fy = dp.get("fiscal_year")
                val = dp.get("value")
                end = dp.get("end_date")
                accn = dp.get("accession_number")
                print(f"   FY{fy} ({end}): {val:,} {unit} [accn: {accn}]")

    await client.close()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

