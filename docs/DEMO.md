# Quantix Demo Guide & Example Queries

This guide demonstrates five realistic questions target users (finance newsletter writers, creators, and independent investors) can ask an AI assistant connected to Quantix, along with the expected high-quality responses with full source verification.

---

### Question 1: Year-over-Year Risk Factors Diff
> **User Prompt:**  
> *"What changed in Apple's (AAPL) Risk Factors between their 2023 and 2024 Form 10-K filings?"*

#### Tool Invoked by Assistant:
`diff_filings(ticker="AAPL", section="risk_factors", form_type="10-K")`

#### Expected Assistant Output:
```markdown
### Year-over-Year Risk Factor Changes for Apple Inc. (AAPL)
**Comparison:** FY2023 10-K (2023-11-03) vs. FY2024 10-K (2024-11-01)  
**Total Changes:** 2 Added Paragraphs, 1 Removed, 3 Materially Reworded (31 Unchanged)

#### 1. Major New Disclosures (Added)
- **Generative AI & Emerging Technologies:** Apple added explicit disclosures regarding research and capital allocation toward proprietary artificial intelligence systems, noting risks around user privacy compliance, computational infrastructure dependencies, and rapid market obsolescence.
- **European Digital Markets Act (DMA) Compliance:** A newly introduced subsection outlines potential business model headwinds stemming from EU regulatory mandates requiring third-party app stores, alternative payment rails, and browser engine unbundling.

#### 2. Retired Disclosures (Removed)
- References to specific post-pandemic supply chain shortages and temporary assembly facility disruptions in Zhengzhou were retired.

#### 3. Why It Matters
Regulatory pressure in the European Union represents an immediate margin risk for Apple’s high-margin Services division (30% App Store take rate). Concurrently, capital intensity is shifting toward AI infrastructure and sovereign regulatory compliance.

**Official Sources:**
- Current Filing: [Apple FY2024 10-K Document](https://www.sec.gov/Archives/edgar/data/320193/000032019324000106/aapl-20240928.htm)
- Prior Filing: [Apple FY2023 10-K Document](https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm)

*Informational only, not investment advice.*
```

---

### Question 2: Multi-Year Financial Trend
> **User Prompt:**  
> *"Can you show me NVIDIA's annual revenue and diluted EPS over the last 3 fiscal years?"*

#### Tools Invoked by Assistant:
1. `get_financials(ticker="NVDA", metric="revenue", periods=3, period_type="annual")`
2. `get_financials(ticker="NVDA", metric="eps_diluted", periods=3, period_type="annual")`

#### Expected Assistant Output:
```markdown
### NVIDIA Corporation (NVDA) - 3-Year Financial Trajectory
*Data extracted directly from official SEC XBRL company facts.*

| Fiscal Year | Period End | Total Revenue (USD) | YoY Growth | Diluted EPS (USD/shares) | Source Accession |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FY2024** | 2024-01-28 | $60,922,000,000 | +126% | $1.19 | `0001045810-24-000021` |
| **FY2025** | 2025-01-26 | $130,497,000,000 | +114% | $2.94 | `0001045810-25-000021` |
| **FY2026** | 2026-01-25 | $215,938,000,000 | +65% | $4.90 | `0001045810-26-000021` |

**Key Takeaways:**
- **Exponential Top-Line Expansion:** Revenue surged over 250% from FY2024 to FY2026, driven by sustained hyperscaler demand for GPU compute clusters (Hopper and Blackwell architectures).
- **Operating Leverage:** Diluted EPS expanded from $1.19 to $4.90, reflecting gross margin expansion above 70%.

**Source Link:** [SEC EDGAR Official Facts for CIK 0001045810](https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json)

*Informational only, not investment advice.*
```

---

### Question 3: Form 8-K Breaking News Alert
> **User Prompt:**  
> *"Did Tesla submit any new 8-K filings recently, and what happened?"*

#### Tool Invoked by Assistant:
`check_new_filings(ticker="TSLA")`

#### Expected Assistant Output:
```markdown
### New Form 8-K Filing Detected for Tesla, Inc. (TSLA)
- **Filing Date:** 2024-11-06
- **Items Triggered:** Item 5.02 (Departure of Directors or Certain Officers; Election of Directors)
- **Accession:** `0001318605-24-000088`

**3-Sentence Plain English Summary:**
Tesla announced that Senior Vice President of Powertrain and Energy Engineering Drew Baglino has resigned effective immediately after 18 years at the company. In the same filing, Tesla confirmed that Vice President of Public Policy Rohan Patel has also stepped down. The executive transitions occur alongside Tesla's global workforce restructuring aimed at streamlining core electric vehicle operations and accelerating autonomous driving initiatives.

**Document Source:** [SEC Archives Direct Filing Link](https://www.sec.gov/Archives/edgar/data/1318605/000131860524000088/tsla-20241106.htm)

*Informational only, not investment advice.*
```

---

### Question 4: Comprehensive Company Brief
> **User Prompt:**  
> *"Give me a complete company briefing for Microsoft (MSFT) combining financial trajectory and recent filings."*

#### Tool Invoked by Assistant:
`company_brief(ticker="MSFT")`

#### Expected Assistant Output:
```markdown
# Quantix Executive Briefing: Microsoft Corporation (MSFT)
*As of 2026-11-08 | SEC CIK: 0000789019*

### 1. Business & Financial Performance Overview
Microsoft demonstrated continued compounding across its Intelligent Cloud and Productivity segments:
- **Revenue:** FY2024: $245.1B | FY2025: $281.7B | FY2026: $331.8B
- **Net Income:** FY2024: $88.1B | FY2025: $101.8B | FY2026: $133.7B
- **Cash & Equivalents:** $110.2B in liquid reserves against $45.8B in long-term debt, preserving an exceptional balance sheet.

### 2. Key Disclosures & Risk Evolution
A paragraph-level diff of Microsoft's latest 10-K reveals expanded risk language around:
- **AI Infrastructure & Energy Constraints:** Explicit warnings regarding regional power grid availability and datacenter cooling capacity necessary to support Azure OpenAI workloads.
- **Cybersecurity & National Security Regulations:** Added disclosure regarding the Secure Future Initiative (SFI) following federal review board recommendations.

### 3. Recent SEC Filings
1. **Form 10-K (2026-07-30):** Annual report covering record Azure growth and Activision Blizzard integration.
2. **Form 8-K (2026-09-18):** Announcement of quarterly dividend increase ($0.83/share) and new $60B share repurchase authorization.

**Sources:**
- [SEC Ticker Directory](https://www.sec.gov/files/company_tickers.json)
- [Microsoft FY2026 10-K](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm)

*Informational only, not investment advice.*
```

---

### Question 5: Substantive Section Inspection
> **User Prompt:**  
> *"Extract the Management Discussion & Analysis (MD&A) section from Apple's latest 10-Q."*

#### Tool Invoked by Assistant:
`get_filing_section(ticker="AAPL", form_type="10-Q", section="mdna")`

#### Expected Assistant Output:
```markdown
### Apple Inc. - Item 2: Management's Discussion and Analysis (Form 10-Q)
**Filing Date:** 2024-08-02 | **Accession:** `0000320193-24-000081`

**Cleaned Excerpt (Character Count: 28,450):**
> "Total net sales increased 5% or $4.0 billion during the three months ended June 29, 2024 compared to the three months ended July 1, 2023, driven by higher net sales of iPad and Services, partially offset by lower net sales of Wearables, Home and Accessories.
>
> Services net sales grew 14% to a new June quarter all-time record of $24.2 billion, propelled by double-digit growth in paid subscriptions across App Store, Cloud, and Apple Music platforms. Gross margin expanded to 46.3% compared to 44.5% in the year-ago quarter..."

**Official Document URL:** [View on SEC EDGAR](https://www.sec.gov/Archives/edgar/data/320193/000032019324000081/aapl-20240629.htm)

*Informational only, not investment advice.*
```

