# Studio Pricing & Compute Cost — Handover for Next Agent

Version: 1.1
Date: 2026-10-05

## Final Decision

The Studio will use **three layers**:

1. **Excel/Google Sheets = internal economics calculator and scenario planning**
2. **Admin Console = live production pricing/configuration**
3. **PostgreSQL = production records and generation data**

Do NOT make the Excel/Google Sheet the production pricing engine.

Do NOT expose complex infrastructure economics to customers.

---

## Current Infrastructure

### Lufi
- Ryzen 9 7900X
- RTX 4060 Ti 8GB
- Hosting/backend
- PostgreSQL/FastAPI/Redis where applicable
- Ollama
- Lightweight ComfyUI workflows
- Can act as a generation worker when workflow/model is supported

### Zoro
- Ryzen 9 9950X
- RTX 5090
- Heavy image generation
- Heavy video generation
- Audio generation
- FFmpeg
- Hyperframes
- Heavy ComfyUI workflows

Electricity rate: **₹8/kWh**

Provisional Zoro heavy-load wall power: **950 W**.
This is only an initial assumption and should later be replaced with measured wall power.

---

## Generation Scheduler

Both machines can run ComfyUI.

Use a central queue and a capability-aware scheduler.

Do NOT simply assign a job to whichever server is free.

Scheduler must check:
- Workflow/model compatibility
- VRAM requirement
- Worker capability
- Worker availability
- Queue length
- Preferred worker
- Fallback worker
- Priority

Examples:
- Heavy video → Zoro preferred
- Heavy image → Zoro preferred
- Audio → Zoro preferred
- Lightweight workflows → Lufi preferred
- Lufi can be fallback for workflows it actually supports

---

# Customer Pricing

Customer pricing must remain simple.

For video:

    customer_credits =
        duration_seconds × credits_per_second

Example:

    1 sec = X credits
    5 sec = 5X
    10 sec = 10X
    15 sec = 15X

The user pays based on requested output duration, NOT actual GPU execution time.

Do not expose electricity, depreciation, GPU runtime, or infrastructure calculations to customers.

Resolution/quality multipliers may be added later:

    final_credits =
        duration × credits_per_second
        × resolution_multiplier
        × quality_multiplier

Start with the simple duration model.

---

# Credits

Example only:

    ₹100 = 1,000 credits

This is not the final package price.

The credit-to-INR relationship is controlled from Admin Console.

When a job is submitted:

1. Calculate required credits.
2. Check balance.
3. Reserve credits.
4. Queue job.
5. Run generation.
6. On success, finalize consumption.
7. On failure, refund according to policy.

Store:
- credits_required
- credits_reserved
- credits_consumed
- credits_refunded

---

# Admin Console

Create:

    Admin
      └── Economics / Pricing

## A. Electricity

Fields:
- electricity_rate_inr_per_kwh

Current:
- ₹8/kWh

Must be editable.

## B. Servers

For each worker store:
- server_id
- server_name
- CPU
- GPU
- VRAM
- role
- idle_power_w
- average_generation_power_w
- max_power_w
- preferred_workflows
- supported_workflows
- active/inactive

Initial Zoro average generation power:
- 950 W

This must be editable.

## C. Workflow Pricing

For each workflow store:
- workflow_id
- workflow_name
- generation_type
- preferred_server
- fallback_servers
- credits_per_second
- base_credits
- resolution_multiplier
- quality_multiplier
- enabled

For video, the primary customer-facing value is:

    credits_per_second

Example:
- Video workflow A → 20 credits/sec

## D. Credit Packages

Store:
- package name
- price INR
- credits
- bonus credits if applicable
- active/inactive

## E. Economics Dashboard — later

Show:
- Revenue
- Credits sold
- Credits consumed
- GPU hours
- Electricity cost
- Estimated total cost
- Profit
- Gross margin
- Failed jobs
- Retry rate
- Worker utilization
- Cost per workflow

Do not build a highly complex real-time cost engine initially.

---

# Internal Cost Calculation

True internal cost is:

    True Cost =
        GPU electricity
      + CPU/system electricity
      + cooling allocation
      + hardware depreciation
      + storage
      + bandwidth
      + model/API licensing
      + failure/retry cost
      + infrastructure allocation

Electricity:

    electricity_cost =
        wall_power_kW
        × runtime_hours
        × electricity_rate

For Zoro provisional assumption:

    0.95 kW × ₹8 = ₹7.60/hour

Therefore:

    ₹0.1267/minute
    ₹0.00211/second

These are electricity costs only and are NOT customer prices.

---

# Hardware Depreciation

Store in Admin Console:
- purchase price
- purchase date
- expected life months
- salvage value
- expected productive hours

Useful calculations:

    monthly_depreciation =
        depreciable_cost / life_months

and eventually:

    depreciation_per_gpu_hour =
        depreciable_cost / productive_gpu_hours

Do not hard-code these values in application code.

---

# Cooling

If AC is dedicated to server operation, allocate appropriate AC cost.

Do not automatically assign all household/office AC cost to every generation.

---

# Storage and Bandwidth

Track:
- input size
- output size
- temporary files
- stored files
- backup storage
- upload bandwidth
- download bandwidth

Eventually calculate storage/bandwidth cost per generation.

---

# Failure / Retry

Track:
- successful jobs
- failed jobs
- retry count

Example:

100 successful outputs requiring 108 actual runs means:

    retry/failure overhead = 108 / 100 = 1.08

Do not permanently hard-code a failure percentage. Measure it from production data.

---

# Production Data to Record

Every generation job should record:

- job_id
- user_id
- workflow_id
- server_id
- generation type
- requested duration
- actual runtime
- success/failure
- retry count
- output size
- credits required
- credits reserved
- credits consumed
- credits refunded
- created_at
- started_at
- completed_at

Later add:
- measured wall power
- estimated electricity cost
- estimated true cost

---

# Excel / Google Sheet

Use the supplied:

    Studio_Generation_Economics_Calculator.xlsx

as the internal economics model.

Recommended sheets:
1. README
2. Servers
3. Workflows
4. Pricing
5. Monthly Model
6. Measurements

Use the spreadsheet to test:
- electricity price
- server power
- utilization
- workflow runtime
- failure rate
- hardware depreciation
- credit rates
- package pricing
- target margin
- monthly revenue
- monthly profit

Google Sheets can be used later if collaboration is needed.

The spreadsheet is a planning/analysis tool.

It is NOT the production billing source of truth.

---

# Development Strategy

Because the Studio is already running, do not stop development to build an advanced costing engine.

### Phase 1 — Now
Build in Admin Console:
- Economics/Pricing section
- Electricity setting
- Server configuration
- Workflow credit pricing
- Credit packages
- Basic job/credit tracking

Use Excel for complex calculations.

### Phase 2
Collect real production data:
- runtime
- success/failure
- retries
- output size
- server
- workflow
- credits

### Phase 3
Measure actual wall power for Lufi and Zoro.

### Phase 4
Add Admin economics dashboard.

### Phase 5
Use actual production economics to adjust workflow credit rates.

---

# Core Principle

Keep these separate:

CUSTOMER:

    "5-second video = X credits"

INTERNAL:

    "This generation cost us ₹X and produced ₹Y gross profit."

The customer-facing system stays simple.

The internal economics system becomes more accurate over time.

---

# Immediate Next Actions

1. Give the next agent this handover.
2. Add Admin → Economics/Pricing section.
3. Add workflow-level credits_per_second.
4. Add credit package configuration.
5. Add credit reservation/consumption/refund.
6. Ensure jobs record server/workflow/runtime/result.
7. Continue using the Excel calculator for business modeling.
8. Later measure actual Lufi/Zoro wall power.
9. Later build the Admin economics dashboard from production data.
