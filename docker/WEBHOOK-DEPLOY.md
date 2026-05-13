# AnGIneer Webhook自动部署系统

## 🎯 系统架构

```
GitHub Actions (构建完成)
    ↓ 发送webhook
    ↓ 带签名验证
服务器 Webhook接收器 (端口9000)
    ↓ 验证签名
    ↓ 登录GHCR
    ↓ 拉取镜像
    ↓ 重启容器
    ↓ 返回结果
完成部署 (延迟<10秒)
```

## 📦 文件说明

| 文件 | 用途 |
|------|------|
| `webhook-server.py` | Webhook接收服务（Flask应用） |
| `angineer-webhook.service` | Systemd服务配置 |
| `webhook-requirements.txt` | Python依赖 |

---

## 🚀 部署步骤

### 步骤1：生成密钥

在服务器上执行：

```bash
# 生成webhook签名密钥（用于验证GitHub请求）
WEBHOOK_SECRET=$(openssl rand -hex 32)
echo "生成的Webhook密钥: $WEBHOOK_SECRET"

# 保存到文件
echo "WEBHOOK_SECRET=$WEBHOOK_SECRET" > /root/angineer-webhook.env

# 生成GitHub PAT token（用于拉取私有镜像）
# 访问 GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
# 勾选 read:packages 权限，生成token
echo "GITHUB_TOKEN=ghp_你的token" >> /root/angineer-webhook.env

# 设置用户名
echo "GITHUB_USERNAME=0mao0" >> /root/angineer-webhook.env

# 设置权限
chmod 600 /root/angineer-webhook.env
```

### 步骤2：安装依赖

```bash
# 安装Python依赖
pip3 install -r /root/AnGIneer/docker/webhook-requirements.txt

# 或者手动安装
pip3 install flask gunicorn
```

### 步骤3：配置Systemd服务

```bash
# 复制服务文件
cp /root/AnGIneer/docker/angineer-webhook.service /etc/systemd/system/

# 编辑服务文件，更新密钥路径
nano /etc/systemd/system/angineer-webhook.service
# 确保 EnvironmentFile=/root/angineer-webhook.env 路径正确

# 重载systemd
systemctl daemon-reload

# 启动服务
systemctl start angineer-webhook

# 设置开机自启
systemctl enable angineer-webhook

# 检查状态
systemctl status angineer-webhook
```

### 步骤4：配置GitHub Secrets

访问 GitHub仓库 → Settings → Secrets and variables → Actions

添加以下secrets：

| Secret名称 | 值 | 说明 |
|-----------|-----|------|
| `DEPLOY_WEBHOOK_URL` | `http://你的服务器IP:9000/webhook/deploy` | Webhook接收地址 |
| `WEBHOOK_SECRET` | 步骤1生成的密钥 | 用于签名验证 |
| `GITHUB_TOKEN` | 你的PAT token | 已有，无需重复添加 |

**示例**：
```
DEPLOY_WEBHOOK_URL = http://123.45.67.89:9000/webhook/deploy
WEBHOOK_SECRET = a1b2c3d4e5f6...（步骤1生成的64位hex字符串）
```

### 步骤5：测试Webhook

#### 方法1：手动触发测试

```bash
# 在服务器上执行
curl -X POST http://localhost:9000/webhook/deploy \
  -H 'Content-Type: application/json' \
  -d '{"action":"deploy","commit":"test123","timestamp":"2024-01-01T00:00:00Z"}'
```

#### 方法2：健康检查

```bash
curl http://localhost:9000/health
# 应该返回：{"status":"healthy","service":"angineer-webhook",...}
```

#### 方法3：查看日志

```bash
# 查看systemd日志
journalctl -u angineer-webhook -f

# 查看应用日志
tail -f /var/log/angineer-webhook.log
```

### 步骤6：触发真实部署

```bash
# 在本地修改代码后提交
git add .
git commit -m "test webhook deploy"
git push origin main

# 观察GitHub Actions日志，应该看到：
# 🔔 触发部署webhook...
# ✅ Webhook已触发，服务器将立即部署

# 在服务器上查看日志
tail -f /var/log/angineer-webhook.log
# 应该看到：
# 🔔 收到部署请求: action=deploy, commit=xxx, time=...
# ✅ GHCR 登录成功
# 📥 开始拉取最新镜像
# 🚀 重新创建容器
# ✅ 部署成功！耗时 xx.x 秒
```

---

## 🔧 高级配置

### 使用Nginx反向代理（推荐）

如果服务器已有Nginx，可以配置反向代理：

```nginx
# /etc/nginx/sites-available/angineer-webhook
server {
    listen 80;
    server_name your-domain.com;

    location /webhook/ {
        proxy_pass http://127.0.0.1:9000/webhook/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 增加超时时间（部署可能需要几分钟）
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
```

然后更新GitHub Secret：
```
DEPLOY_WEBHOOK_URL = http://your-domain.com/webhook/deploy
```

### 使用HTTPS（生产环境推荐）

```bash
# 使用Let's Encrypt获取免费证书
certbot --nginx -d your-domain.com

# webhook URL变为：
DEPLOY_WEBHOOK_URL = https://your-domain.com/webhook/deploy
```

### 防火墙配置

```bash
# 开放webhook端口（如果不用Nginx）
ufw allow 9000/tcp

# 或者仅允许GitHub Actions IP访问
# GitHub Actions IP范围：https://api.github.com/meta
```

---

## 🐛 故障排查

### 问题1：Webhook服务无法启动

```bash
# 检查Python版本
python3 --version  # 需要 >= 3.7

# 检查依赖
pip3 list | grep flask

# 检查环境变量文件
cat /root/angineer-webhook.env

# 查看详细错误
journalctl -u angineer-webhook -n 50
```

### 问题2：签名验证失败

```bash
# 检查GitHub Secret和服务器配置是否一致
# GitHub: Settings → Secrets → WEBHOOK_SECRET
# 服务器: /root/angineer-webhook.env 中的 WEBHOOK_SECRET

# 临时禁用签名验证（仅用于调试）
# 编辑 webhook-server.py，设置 WEBHOOK_SECRET = ''
```

### 问题3：GHCR登录失败

```bash
# 手动测试登录
echo "ghp_你的token" | docker login ghcr.io -u 0mao0 --password-stdin

# 检查token权限
# 需要勾选 read:packages 权限
```

### 问题4：容器未更新

```bash
# 检查镜像是否拉取成功
docker images | grep angineer

# 检查容器状态
cd /root/AnGIneer/docker
docker compose ps

# 查看容器日志
docker compose logs --tail=50
```

---

## 📊 性能优化

### 使用Gunicorn（生产环境）

```bash
# 安装gunicorn
pip3 install gunicorn

# 修改systemd服务
nano /etc/systemd/system/angineer-webhook.service
# 将 ExecStart 改为：
ExecStart=/usr/bin/gunicorn \
  --bind 0.0.0.0:9000 \
  --workers 2 \
  --threads 4 \
  --timeout 300 \
  --access-logfile /var/log/angineer-webhook-access.log \
  --error-logfile /var/log/angineer-webhook-error.log \
  webhook-server:app

# 重启服务
systemctl restart angineer-webhook
```

---

## 🔐 安全建议

1. **定期轮换密钥**（每90天）
   ```bash
   # 重新生成密钥
   WEBHOOK_SECRET=$(openssl rand -hex 32)
   echo "WEBHOOK_SECRET=$WEBHOOK_SECRET" > /root/angineer-webhook.env
   
   # 更新GitHub Secret
   
   # 重启服务
   systemctl restart angineer-webhook
   ```

2. **限制访问来源**
   - 使用防火墙仅允许GitHub Actions IP访问
   - 或使用Nginx的`allow/deny`指令

3. **监控异常请求**
   ```bash
   # 查看失败的webhook请求
   grep "签名验证失败" /var/log/angineer-webhook.log
   ```

4. **备份配置**
   ```bash
   # 定期备份
   tar -czf /root/backup/webhook-config-$(date +%Y%m%d).tar.gz \
     /root/angineer-webhook.env \
     /etc/systemd/system/angineer-webhook.service
   ```

---

## 📝 日志说明

### Webhook服务日志

位置：`/var/log/angineer-webhook.log`

```
[2024-01-01 12:00:00] INFO: 🚀 AnGIneer Webhook服务启动，监听端口 9000
[2024-01-01 12:00:05] INFO: 🔔 收到部署请求: action=deploy, commit=a1b2c3d4, time=...
[2024-01-01 12:00:05] INFO: ✅ GHCR 登录成功
[2024-01-01 12:00:10] INFO: 📥 开始拉取最新镜像 (commit: a1b2c3d4)
[2024-01-01 12:00:15] INFO: 🚀 重新创建容器...
[2024-01-01 12:00:20] INFO: ✅ 部署成功！耗时 15.2 秒
```

### Systemd日志

```bash
journalctl -u angineer-webhook -f
```

---

## 🎉 完成！

现在你的部署流程是：

1. 本地修改代码 → `git push`
2. GitHub Actions自动构建镜像 → 推送到GHCR
3. 构建完成 → 触发webhook
4. 服务器收到webhook → 验证签名 → 拉取镜像 → 重启容器
5. **部署完成！延迟<10秒** ⚡

相比cron轮询（5分钟延迟），webhook方案实现了**秒级自动部署**！
