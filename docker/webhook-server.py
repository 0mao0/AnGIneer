#!/usr/bin/env python3
"""
AnGIneer Webhook接收器
监听GitHub Actions的部署通知，自动执行docker compose部署
"""
import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from flask import Flask, request, jsonify

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('/var/log/angineer-webhook.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME', '0mao0')
DEPLOY_DIR = Path(os.getenv('DEPLOY_DIR', '/root/AnGIneer/docker'))
ALLOWED_ACTIONS = ['deploy', 'redeploy', 'rollback']


def verify_signature(payload: bytes, signature: str) -> bool:
    """验证GitHub webhook签名（防止伪造请求）"""
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET 未设置，跳过签名验证（不安全！）")
        return True
    
    expected_sig = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(f"sha256={expected_sig}", signature)


def login_ghcr() -> bool:
    """登录GitHub Container Registry"""
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN 未设置，无法拉取私有镜像")
        return False
    
    try:
        result = subprocess.run(
            ['docker', 'login', 'ghcr.io', '-u', GITHUB_USERNAME, '--password-stdin'],
            input=GITHUB_TOKEN.encode('utf-8'),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        if result.returncode == 0:
            logger.info("✅ GHCR 登录成功")
            return True
        else:
            logger.error(f"❌ GHCR 登录失败: {result.stderr.decode('utf-8')}")
            return False
    except Exception as e:
        logger.error(f"❌ GHCR 登录异常: {e}")
        return False


REGISTRY = os.getenv('REGISTRY', 'ghcr.io')
IMAGE_PREFIX = os.getenv('IMAGE_PREFIX', '0mao0/angineer')

SERVICE_IMAGE_MAP = {
    'frontend': f'{REGISTRY}/{IMAGE_PREFIX}-frontend',
    'api-server': f'{REGISTRY}/{IMAGE_PREFIX}-api',
}


def _run_cmd(cmd, timeout=120):
    """执行命令并返回 (returncode, stdout_str, stderr_str)"""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout
    )
    return (
        result.returncode,
        result.stdout.decode('utf-8', errors='replace'),
        result.stderr.decode('utf-8', errors='replace')
    )


def pull_service_image(service_name, tag):
    """拉取指定服务的镜像"""
    image_ref = SERVICE_IMAGE_MAP.get(service_name)
    if not image_ref:
        logger.error(f"❌ 未知服务: {service_name}")
        return False

    full_ref = f"{image_ref}:{tag}"
    logger.info(f"📥 拉取 {full_ref}")
    rc, stdout, stderr = _run_cmd(['docker', 'pull', full_ref], timeout=600)

    if rc != 0:
        logger.error(f"❌ 拉取失败 {full_ref}: {stderr}")
        return False

    logger.info(f"✅ 拉取完成 {full_ref}")
    return True


def retag_to_latest(service_name, sha_tag):
    """将 SHA tag 重新标记为 latest，使 docker compose up 使用新镜像"""
    image_ref = SERVICE_IMAGE_MAP.get(service_name)
    if not image_ref:
        return False

    sha_ref = f"{image_ref}:{sha_tag}"
    latest_ref = f"{image_ref}:latest"

    rc, _, stderr = _run_cmd(['docker', 'tag', sha_ref, latest_ref], timeout=30)
    if rc != 0:
        logger.error(f"❌ 重新标记失败 {sha_ref} -> {latest_ref}: {stderr}")
        return False

    logger.info(f"🏷️ 标记 {sha_ref} -> {latest_ref}")
    return True


def execute_deploy(commit_sha: str, action: str = 'deploy', services=None) -> Dict[str, Any]:
    """执行部署流程，支持按服务增量拉取"""
    start_time = datetime.now()
    target_services = services if services else list(SERVICE_IMAGE_MAP.keys())

    try:
        os.chdir(DEPLOY_DIR)

        if not login_ghcr():
            return {
                'success': False,
                'error': 'GHCR认证失败',
                'duration': (datetime.now() - start_time).total_seconds()
            }

        for svc in target_services:
            if not pull_service_image(svc, commit_sha):
                if not pull_service_image(svc, 'latest'):
                    return {
                        'success': False,
                        'error': f'拉取 {svc} 镜像失败',
                        'duration': (datetime.now() - start_time).total_seconds()
                    }
                logger.warning(f"⚠️ {svc} 的 SHA tag 不存在，回退到 latest")
            else:
                retag_to_latest(svc, commit_sha)

        logger.info(f"🚀 重新创建容器 (服务: {', '.join(target_services)})...")
        up_result = subprocess.run(
            ['docker', 'compose', 'up', '-d', '--force-recreate', '--no-deps'] + target_services,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120
        )

        if up_result.returncode != 0:
            stderr_text = up_result.stderr.decode('utf-8', errors='replace')
            logger.error(f"容器启动失败: {stderr_text}")
            return {
                'success': False,
                'error': stderr_text,
                'duration': (datetime.now() - start_time).total_seconds()
            }

        logger.info("🧹 清理旧镜像...")
        subprocess.run(
            ['docker', 'image', 'prune', '-f'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60
        )

        logger.info("⏳ 等待服务启动...")
        subprocess.run(['sleep', '10'], timeout=15)

        ps_result = subprocess.run(
            ['docker', 'compose', 'ps'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )

        ps_stdout = ps_result.stdout.decode('utf-8', errors='replace')
        if 'running' in ps_stdout or 'Up' in ps_stdout:
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ 部署成功！耗时 {duration:.1f} 秒")

            return {
                'success': True,
                'commit': commit_sha,
                'action': action,
                'services': target_services,
                'duration': duration,
                'containers': ps_stdout
            }
        else:
            logger.error("⚠️ 容器状态异常")
            return {
                'success': False,
                'error': '容器未正常运行',
                'containers': ps_stdout,
                'duration': (datetime.now() - start_time).total_seconds()
            }

    except subprocess.TimeoutExpired:
        logger.error("❌ 部署超时")
        return {
            'success': False,
            'error': '部署超时',
            'duration': (datetime.now() - start_time).total_seconds()
        }
    except Exception as e:
        logger.error(f"❌ 部署异常: {e}")
        return {
            'success': False,
            'error': str(e),
            'duration': (datetime.now() - start_time).total_seconds()
        }
    finally:
        subprocess.run(['docker', 'logout', 'ghcr.io'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({
        'status': 'healthy',
        'service': 'angineer-webhook',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/webhook/deploy', methods=['POST'])
def handle_deploy():
    """处理GitHub Actions的部署webhook"""
    try:
        signature = request.headers.get('X-Hub-Signature-256', '')
        payload = request.data
        
        if not verify_signature(payload, signature):
            logger.warning("❌ 签名验证失败，拒绝请求")
            return jsonify({'error': 'Invalid signature'}), 403
        
        data = request.get_json()
        
        action = data.get('action', 'deploy')
        commit_sha = data.get('commit', 'unknown')
        timestamp = data.get('timestamp', datetime.now().isoformat())
        services = data.get('services')
        if isinstance(services, str):
            services = services.split()
        
        logger.info(f"🔔 收到部署请求: action={action}, commit={commit_sha[:8]}, time={timestamp}, services={services or '全部'}")
        
        if action not in ALLOWED_ACTIONS:
            return jsonify({'error': f'Invalid action: {action}'}), 400
        
        result = execute_deploy(commit_sha, action, services)
        
        if result['success']:
            return jsonify({
                'status': 'success',
                'message': '部署成功',
                **result
            }), 200
        else:
            return jsonify({
                'status': 'failed',
                'message': result.get('error', '部署失败'),
                **result
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Webhook处理异常: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/webhook/github', methods=['POST'])
def handle_github_event():
    """处理GitHub原生事件（可选：支持repository webhook）"""
    event_type = request.headers.get('X-GitHub-Event', '')
    
    if event_type == 'push':
        data = request.get_json()
        ref = data.get('ref', '')
        
        if ref == 'refs/heads/main':
            commit_sha = data.get('after', 'unknown')
            logger.info(f"📦 检测到main分支push: {commit_sha[:8]}")
            
            result = execute_deploy(commit_sha, 'deploy')
            return jsonify(result), 200 if result['success'] else 500
    
    return jsonify({'status': 'ignored', 'event': event_type}), 200


if __name__ == '__main__':
    port = int(os.getenv('WEBHOOK_PORT', 9000))
    logger.info(f"🚀 AnGIneer Webhook服务启动，监听端口 {port}")
    logger.info(f"📁 部署目录: {DEPLOY_DIR}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )
