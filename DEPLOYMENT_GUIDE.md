# 🚀 Deployment Guide

## tl;dr - Recommended Approach

**For most users**: Use **Option 1: Simple Cloud VM** - it's the easiest, most reliable, and cost-effective approach.

---

## ❌ Why NOT Supabase Edge Functions?

Edge Functions seem appealing but have **critical limitations** for this orchestrator:

- **⏱️ Timeout Issues**: 30-60 second limits (orchestrator cycles can take longer)
- **🥶 Cold Starts**: Delays when scaling workers urgently  
- **🔒 Resource Limits**: May struggle with large worker lists
- **🐛 Debugging**: Harder to troubleshoot than containers
- **📊 Monitoring**: Limited observability compared to container deployments

**Verdict**: Edge Functions are better for simple, fast operations. Use containers for orchestration.

---

## 🎯 Deployment Options Compared

| Option | Complexity | Cost | Reliability | Scalability | Best For |
|--------|------------|------|-------------|-------------|----------|
| **VM + Cron** | ⭐ | $ | ⭐⭐⭐ | ⭐⭐ | Most users |
| **Docker Compose** | ⭐⭐ | $ | ⭐⭐⭐ | ⭐ | Local/small deployments |
| **AWS ECS** | ⭐⭐⭐ | $$ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | AWS users |
| **Kubernetes** | ⭐⭐⭐⭐ | $$$ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Large scale |
| **Google Cloud Run** | ⭐⭐ | $$ | ⭐⭐⭐ | ⭐⭐⭐ | GCP users |

---

## 🥇 Option 1: Simple Cloud VM (Recommended)

**Perfect for**: Most users, getting started, reliable operation

### Step-by-Step Setup

#### 1. Create a Small VM
```bash
# AWS EC2 (t3.micro)
# Google Cloud (e2-micro) 
# DigitalOcean ($6/month droplet)
# Any cloud provider - you just need Ubuntu/Debian
```

#### 2. Install Dependencies
```bash
# SSH into your VM
ssh your-vm

# Install Python and Git
sudo apt update
sudo apt install -y python3 python3-pip git cron

# Clone your repository  
git clone https://github.com/yourusername/your-orchestrator-repo.git
cd your-orchestrator-repo

# Install Python dependencies
pip3 install -r requirements.txt
```

#### 3. Configure Environment
```bash
# Copy and edit environment variables
cp env.example .env
nano .env

# Add your actual credentials:
# SUPABASE_URL=https://your-project.supabase.co
# SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
# RUNPOD_API_KEY=your_runpod_api_key
# etc.
```

#### 4. Test the Setup
```bash
# Test connections
python3 scripts/test_supabase.py
python3 scripts/test_runpod.py

# Test single orchestrator run
python3 -m orchestrator.main single
```

#### 5. Set Up Cron (Every 30 Seconds)
```bash
# Edit crontab
crontab -e

# Add these lines for 30-second intervals:
* * * * * cd /home/ubuntu/your-orchestrator-repo && python3 -m orchestrator.main single >> /var/log/orchestrator.log 2>&1
* * * * * sleep 30 && cd /home/ubuntu/your-orchestrator-repo && python3 -m orchestrator.main single >> /var/log/orchestrator.log 2>&1
```

#### 6. Monitor
```bash
# Watch logs
tail -f /var/log/orchestrator.log

# Check status  
python3 -m orchestrator.main status

# Run dashboard
python3 scripts/dashboard.py
```

### 💰 Cost: ~$5-15/month

---

## 🐳 Option 2: Docker Compose (Local/Development)

**Perfect for**: Local development, testing, small deployments

### Setup
```bash
# 1. Copy environment file
cp env.example .env
# Edit .env with your credentials

# 2. Build and run
cd deployment/
docker-compose up -d

# 3. Test single run
docker-compose --profile testing run orchestrator-single

# 4. View logs
docker-compose logs -f orchestrator

# 5. Run dashboard
docker-compose --profile monitoring up dashboard
```

### 💰 Cost: Just your server costs

---

## ☁️ Option 3: AWS ECS Fargate

**Perfect for**: AWS users, production workloads, automatic scaling

### Prerequisites
- AWS CLI configured
- ECR repository created
- Secrets Manager configured

### Step-by-Step

#### 1. Build and Push Image
```bash
# Build image
docker build -f deployment/Dockerfile -t runpod-orchestrator .

# Tag for ECR
docker tag runpod-orchestrator:latest YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/runpod-orchestrator:latest

# Push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com
docker push YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/runpod-orchestrator:latest
```

#### 2. Store Secrets
```bash
# Create secrets in AWS Secrets Manager
aws secretsmanager create-secret \
  --name runpod-orchestrator \
  --secret-string '{
    "SUPABASE_URL":"your-url",
    "SUPABASE_SERVICE_ROLE_KEY":"your-key", 
    "RUNPOD_API_KEY":"your-key",
    "RUNPOD_CONTAINER_IMAGE":"your-image"
  }'
```

#### 3. Create ECS Resources
```bash
# Update deployment/aws-ecs-task-definition.json with your values

# Register task definition
aws ecs register-task-definition --cli-input-json file://deployment/aws-ecs-task-definition.json

# Create cluster
aws ecs create-cluster --cluster-name runpod-orchestrator

# Create service with EventBridge scheduling
aws events put-rule \
  --name runpod-orchestrator-schedule \
  --schedule-expression "rate(1 minute)"

aws events put-targets \
  --rule runpod-orchestrator-schedule \
  --targets "Id"="1","Arn"="arn:aws:ecs:us-east-1:YOUR_ACCOUNT:cluster/runpod-orchestrator","RoleArn"="arn:aws:iam::YOUR_ACCOUNT:role/ecsTaskExecutionRole","EcsParameters"="{\"TaskDefinitionArn\":\"arn:aws:ecs:us-east-1:YOUR_ACCOUNT:task-definition/runpod-orchestrator:1\"}"
```

### 💰 Cost: ~$15-30/month (depending on usage)

---

## ⚓ Option 4: Kubernetes

**Perfect for**: Large scale, existing K8s infrastructure, high availability

### Step-by-Step

#### 1. Build and Push Image
```bash
# Build and push to your container registry
docker build -f deployment/Dockerfile -t your-registry/runpod-orchestrator:latest .
docker push your-registry/runpod-orchestrator:latest
```

#### 2. Create Secrets
```bash
# Encode your secrets
echo -n "your-supabase-url" | base64
echo -n "your-service-role-key" | base64  
echo -n "your-runpod-api-key" | base64
echo -n "your-container-image" | base64

# Edit deployment/kubernetes-cronjob.yaml with encoded values
```

#### 3. Deploy
```bash
# Apply the configuration
kubectl apply -f deployment/kubernetes-cronjob.yaml

# Check status
kubectl get cronjobs
kubectl get jobs
kubectl logs -l job-name=runpod-orchestrator-xxxxx
```

#### 4. Optional: Continuous Mode
```bash
# Deploy the continuous version instead
kubectl apply -f deployment/kubernetes-cronjob.yaml
# (This includes the Deployment section)
```

### 💰 Cost: Varies by cluster size

---

## 🌩️ Option 5: Google Cloud Run

**Perfect for**: GCP users, serverless preference, occasional workloads

### Step-by-Step

#### 1. Build and Push
```bash
# Build for Cloud Run
docker build -f deployment/Dockerfile -t gcr.io/YOUR_PROJECT/runpod-orchestrator:latest .

# Push to GCR
docker push gcr.io/YOUR_PROJECT/runpod-orchestrator:latest
```

#### 2. Create Secrets
```bash
# Create secret in Secret Manager
gcloud secrets create orchestrator-secrets --data-file=.env
```

#### 3. Deploy Service
```bash
# Deploy to Cloud Run
gcloud run deploy runpod-orchestrator \
  --image gcr.io/YOUR_PROJECT/runpod-orchestrator:latest \
  --platform managed \
  --region us-central1 \
  --no-allow-unauthenticated \
  --memory 512Mi \
  --timeout 60 \
  --set-env-vars MIN_ACTIVE_GPUS=2,MAX_ACTIVE_GPUS=10
```

#### 4. Schedule with Cloud Scheduler
```bash
# Create scheduler job
gcloud scheduler jobs create http orchestrator-trigger \
  --schedule="*/1 * * * *" \
  --uri="https://runpod-orchestrator-xxxxx-uc.a.run.app" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@YOUR_PROJECT.iam.gserviceaccount.com
```

### 💰 Cost: Pay per invocation (~$5-20/month)

---

## 🔧 Configuration Tips

### Environment Variables Priority Order
1. `.env` file (for local development)
2. Container environment variables  
3. Cloud secret managers (recommended for production)

### Scaling Parameters
```bash
# Conservative settings (start here)
MIN_ACTIVE_GPUS=1
MAX_ACTIVE_GPUS=5
TASKS_PER_GPU_THRESHOLD=2

# Production settings (adjust based on your workload)
MIN_ACTIVE_GPUS=2
MAX_ACTIVE_GPUS=20
TASKS_PER_GPU_THRESHOLD=3
```

### Monitoring Setup
```bash
# Add monitoring endpoints to your deployment
# Most cloud providers support health checks at:
GET /health   # Add this endpoint to orchestrator/main.py if needed
```

---

## 🚨 Production Checklist

### Security
- [ ] Use secret managers (not .env files)
- [ ] Restrict network access to orchestrator
- [ ] Use least-privilege IAM roles
- [ ] Enable logging and monitoring
- [ ] Set up alerts for failures

### Reliability  
- [ ] Configure health checks
- [ ] Set up proper logging
- [ ] Monitor disk space (for logs)
- [ ] Test failure scenarios
- [ ] Document runbooks

### Cost Control
- [ ] Set MAX_ACTIVE_GPUS limits
- [ ] Monitor spend with cloud billing alerts  
- [ ] Test with small limits first
- [ ] Consider budget-based auto-shutdown

---

## 🔍 Monitoring Your Deployment

### Real-time Dashboard
```bash
# Local monitoring
python3 scripts/dashboard.py

# Export metrics for external monitoring
python3 scripts/dashboard.py --export
```

### Log Monitoring
```bash
# VM deployment
tail -f /var/log/orchestrator.log

# Docker  
docker-compose logs -f orchestrator

# Kubernetes
kubectl logs -f deployment/runpod-orchestrator-continuous

# Cloud providers: use their native logging (CloudWatch, Stackdriver, etc.)
```

### Alerts Setup
Monitor these metrics:
- Worker spawn failures
- High task queue depth
- Orchestrator execution failures  
- High GPU costs
- Heartbeat failures

---

## 🎯 Which Option Should You Choose?

### 🥇 **Start with Option 1 (VM + Cron)** if you:
- Want to get running quickly
- Need reliable, predictable operation
- Have moderate scale requirements  
- Want to minimize complexity

### Choose **Container options** if you:
- Already use that platform (AWS/GCP/K8s)
- Need high availability
- Want automatic scaling of the orchestrator itself
- Have existing DevOps infrastructure

### ⚠️ **Avoid Edge Functions** because:
- Orchestrator cycles can exceed timeout limits
- Cold starts delay urgent scaling decisions
- Debugging is much harder
- Container approaches are more reliable

Remember: The orchestrator is critical infrastructure. **Reliability > Complexity**. Start simple and scale up as needed! 🚀 