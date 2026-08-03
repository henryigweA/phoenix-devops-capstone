# Phoenix Inventory API — DevOps Capstone

A small Flask API, deployed to Azure the way a real DevOps engineer would do it:
infrastructure as code, containerized, automated deployment, and monitored.
This README documents exactly how it was built, step by step, including the
real errors hit along the way and how each one was fixed — because in real
DevOps work, the errors are half the job.

---

## 1. What this project actually is

**The app:** a tiny in-memory inventory API (Flask, Python) — `GET /health`,
`GET /products`, `POST /products`, `GET /products/<id>`. Deliberately simple —
no database, no frontend — so the DevOps work is the actual point.

**The mission:** take this app from "runs on one laptop" to "runs in Azure,
redeploys itself automatically on every push, and tells someone if it's
unhealthy" — without ever touching the app's own logic.

## 2. Architecture — the final picture

```
Resource Group: rg-phoenix-dev  (South Africa North)
│
├── VNet (10.0.0.0/16)
│    └── Subnet snet-web (10.0.1.0/24)
│         ├── NSG nsg-web
│         │     100: Allow port 5000 (app's own port)
│         │     110: Allow port 80  (public web traffic)
│         └── AKS node(s) live here
│
├── ACR: acrphoenixdev001        → stores the Docker image
├── AKS: aks-phoenix-dev         → runs the container
│    └── Deployment: phoenix-api → keeps 1 pod alive
│         └── Service: phoenix-api-service (LoadBalancer)
│              → public IP, forwards :80 → pod's :5000
│
├── Log Analytics: log-phoenix-dev  → stores logs/metrics
│    └── Container Insights (oms_agent) ships AKS logs here
│
└── Monitor Alert: phoenix-api-restart-alert
     → checks every 5 min: any pod restarted > 2 times?
     → if yes, emails via Action Group ag-phoenix-alerts
```

**How a request actually flows:**
```
Browser/curl → Public IP :80 → NSG (checks port 80 is allowed)
  → Load Balancer/Service → forwards to pod's :5000 → Flask answers
```

**How a deployment actually flows (after Row 6):**
```
git push → GitHub Actions wakes up → logs into Azure as a robot
  (Service Principal) → builds Docker image → pushes to ACR
  → tells AKS to swap to the new image → old pod replaced, zero downtime
```

## 3. Tools installed and set up

| Tool | Why | Note |
|---|---|---|
| Python + pip | Run the app | |
| Docker Desktop | Build/run containers | |
| Terraform | Provision Azure infra as code | Had to be manually downloaded + added to Windows PATH — see Error Log |
| Azure CLI (`az`) | Talk to Azure, log in | |
| `kubectl` | Talk to the AKS cluster | Comes bundled with Docker Desktop / installed separately |
| Git + GitHub | Version control, trigger pipeline | |

---

## 4. Step-by-step build order

### Row 1 — The app itself
Wrote `app.py` (Flask, 4 routes) + `requirements.txt`. Ran it locally with
`python app.py`, tested every route with `curl` — this is the habit to
repeat for *any* app you're ever handed: read the `@app.get`/`@app.post`
lines in the source code — that list **is** your complete test plan. Don't
guess at endpoints; read them off the code.

### Row 2 — Dockerfile
Packaged the app into an image.

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 5000
CMD ["python", "app.py"]
```

Built and ran it locally first, before touching Azure at all:
```bash
docker build -t phoenix-api:1.0 .
docker run -p 5000:5000 phoenix-api:1.0
curl http://localhost:5000/health
```

### Row 3 — Terraform: Networking
Wrote `terraform/main.tf` + `variables.tf`: Resource Group, VNet, Subnet, NSG
(with a rule allowing port 5000 in). Ran:
```bash
terraform init
terraform plan
terraform apply
```

### Row 4 — Terraform: ACR + AKS
Extended the same `main.tf` with the Container Registry, the AKS cluster
(placed inside the subnet from Row 3), and a role assignment giving AKS
permission to pull images from ACR using a **managed identity** — no stored
password anywhere.

### Row 5 — First manual deployment
```bash
az acr login --name acrphoenixdev001
docker tag phoenix-api:1.0 acrphoenixdev001.azurecr.io/phoenix-api:1.0
docker push acrphoenixdev001.azurecr.io/phoenix-api:1.0

az aks get-credentials --resource-group rg-phoenix-dev --name aks-phoenix-dev
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```
Got a public IP from `kubectl get service phoenix-api-service`, hit it with
`curl` — **first time the app was live on the real internet.**

### Row 6-7 — GitHub Actions (CI/CD)
Created a **Service Principal** (a "robot" Azure identity for GitHub to log
in as, scoped only to this one resource group):
```bash
az ad sp create-for-rbac --name "phoenix-github-actions" --role contributor \
  --scopes /subscriptions/<id>/resourceGroups/rg-phoenix-dev --sdk-auth
```
Stored the 4 output values as GitHub repo secrets (`AZURE_CLIENT_ID`,
`AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`) under
**Settings → Secrets and variables → Actions**. Wrote
`.github/workflows/deploy.yml` to automate: checkout → Azure login → build
& push image (tagged with the git commit SHA) → get AKS credentials →
`kubectl set image` to trigger a rolling update. Every `git push` to `main`
now redeploys automatically.

### Row 8 — Observability
Added a Log Analytics Workspace, wired it to AKS via `oms_agent` (this
enables **Container Insights** — the agent that actually ships pod
logs/metrics into the workspace), and a scheduled alert rule: if any
`phoenix-api` pod restarts more than 2 times within a 5-minute window, email
via an Action Group. Verified for real by deliberately deleting pods to
trigger restarts and confirming the email arrived.

---

## 5. Error log — what actually went wrong, and the fix

Real projects don't go in a straight line. Here's every real blocker hit
during this build, kept in for anyone following this later.

| # | Symptom | Real Cause | Fix |
|---|---|---|---|
| 1 | `terraform: command not found` | Terraform wasn't installed / not on PATH | Downloaded the correct **Windows AMD64** zip (first download was accidentally the macOS version — different OS builds aren't interchangeable), extracted it, added its folder to Windows PATH, restarted terminal *and* PC |
| 2 | `docker build -t phoenix-api:1.0` → `requires 1 argument` | Forgot the trailing `.` (the build context path) | `docker build -t phoenix-api:1.0 .` — the dot is a required argument, not optional |
| 3 | `dial tcp: lookup management.azure.com: no such host` (recurring, throughout) | Unstable local network/DNS — Azure's API momentarily unreachable | Usually fixed by just retrying the same command. When a longer `terraform apply` kept dying mid-operation, switched to a single, fast, direct `az` CLI command instead (less time exposed to a network drop) |
| 4 | `terraform import` → path got mangled into `C:/Program Files/Git/subscriptions/...` | Git Bash on Windows auto-converts any argument starting with `/` into a Windows file path | Prefix the command with `MSYS_NO_PATHCONV=1` to disable that auto-conversion for one command |
| 5 | `terraform apply` on AKS → `A resource ... already exists ... needs to be imported` | An earlier `apply` actually succeeded in Azure, but got interrupted before saving that success to the local state file (state/reality mismatch) | Chose to delete the orphaned resources via `az aks delete` / `az acr delete` and let Terraform recreate them cleanly, rather than importing |
| 6 | `apply` → `OIDCIssuerFeatureCannotBeDisabled` | Azure auto-enabled a feature our `.tf` code never mentioned; Terraform tried to "unset" it back to default, Azure refused | Added `oidc_issuer_enabled = true` explicitly to the code, matching real state, instead of leaving it unset |
| 7 | Every `plan` kept showing the same `upgrade_settings` diff, even right after a successful apply | Same pattern as #6 — Azure auto-set node pool upgrade defaults our code didn't declare | Added an explicit `upgrade_settings { max_surge = "10%" }` block to match reality |
| 8 | App deployed, but `curl <public-ip>/health` → connection refused | NSG only had a rule allowing port **5000** (the app's internal port); the public-facing Service used port **80** | Added a second NSG rule allowing port 80 inbound. (Classic case of "network layer" and "app's own port" being two separate concerns — see Architecture diagram) |
| 9 | First `git push` → `413`/slow push, ~53MB payload | No `.gitignore` yet — `.venv/`, Terraform's `.terraform/` provider binaries, and `terraform.tfstate` all got committed by accident | Created a proper `.gitignore`, ran `git rm -r --cached` on the offending files/folders to untrack them (without deleting them locally), recommitted clean |
| 10 | New pod briefly showed `CrashLoopBackOff` after a pipeline deploy | A bad code push (unrelated to infra) | Old pod kept serving traffic the whole time — this is the rolling-update safety net working correctly; a later push with corrected code resolved it |

## 6. "Don't just trust the output" — verification commands

The single most important DevOps habit: a tool saying "success" isn't the
same as confirming it yourself, independently, a different way. These are
the checks used throughout this build instead of just believing a script.

**Is the resource group / resources actually there?**
```bash
az group list -o table
az resource list -g rg-phoenix-dev -o table
```

**Does the AKS cluster actually exist and is it healthy?**
```bash
az aks list -g rg-phoenix-dev -o table
kubectl get nodes
```
Look for `ProvisioningState: Succeeded` and `STATUS: Ready`.

**Is the image actually sitting in ACR?**
```bash
az acr repository list --name acrphoenixdev001 -o table
az acr repository show-tags --name acrphoenixdev001 --repository phoenix-api -o table
```

**Is the app pod actually running, not just "applied"?**
```bash
kubectl get pods
```
Look for `STATUS: Running` and `READY: 1/1`, not `Pending` or `CrashLoopBackOff`.

**Did the NSG rule actually get created, not just planned?**
```bash
az network nsg rule list --resource-group rg-phoenix-dev --nsg-name nsg-web -o table
```

**Is the app actually reachable from the real internet (not just from inside Azure)?**
```bash
curl http://<public-ip>/health
```

**Does Terraform's state actually match real Azure, right now?**
```bash
terraform plan
```
A truly healthy setup shows `No changes. Your infrastructure matches the
configuration.` — if it shows anything else, reality and code have drifted
and need reconciling before doing anything further.

**Did the GitHub Actions pipeline actually deploy something new, not just run green?**
```bash
kubectl get pods
```
Check the pod's `AGE` — it should be freshly created, matching when the
pipeline ran, not an old pod that was already there.

---

## 7. Key concepts, in one line each

- **Resource Group** — a lifecycle folder; nothing more, no networking of its own.
- **VNet/Subnet** — your own private address space, sliced into segments for blast-radius control.
- **NSG** — a checklist, read top to bottom by priority number, first match wins.
- **ACR** — the shelf where Docker images live.
- **AKS** — the engine that actually runs containers, pulled from that shelf.
- **Pod vs. Node** — a pod is a running container; a node is the real VM it runs on. Never nested inside another VM — siblings in the same resource group.
- **Deployment** — keeps N pods alive, restarts crashed ones, automatically.
- **Service** — a stable, permanent address that finds whichever pods currently match a label, even as they restart. The public IP lives here, not on any pod or node.
- **Terraform state** — Terraform's memory of what it created; source of truth for "what's mine to manage."
- **Managed identity** — an identity Azure manages for a resource, with no password to ever leak.
- **Service Principal** — a "robot" identity, used so GitHub Actions can log into Azure without a human typing a password.
- **CI/CD pipeline** — has no memory between runs; it reruns the entire script every time, top to bottom, on a brand-new disposable machine.

---

## 8. What's next (not yet built)

- A real database (currently in-memory, resets on every pod restart)
- A frontend
- Multiple replicas / horizontal autoscaling (currently pinned to 1 node, 1 pod, for cost control on a free-tier subscription)
- Multi-region / hub-and-spoke networking (concept-level only, per the original roadmap)
- Porting one module to AWS or GCP, to prove the Terraform patterns genuinely transfer