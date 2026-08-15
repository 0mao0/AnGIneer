#!/bin/bash
# AnGIneer 服务器端部署脚本（由 deploy-local.sh 调用）
# 用法: bash deploy.sh [选项]
#   --build-only  仅构建镜像，不启动服务
#   --stop        停止所有服务
#   --restart     重启所有服务
#   --logs        查看实时日志
#   --status      查看服务状态

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"

BUILD_ONLY=false
ACTION="deploy"

for arg in "$@"; do
    case $arg in
        --build-only) BUILD_ONLY=true ;;
        --prepare)    ACTION="prepare" ;;
        --stop)       ACTION="stop" ;;
        --restart)    ACTION="restart" ;;
        --logs)       ACTION="logs" ;;
        --status)     ACTION="status" ;;
    esac
done

check_prerequisites() {
    echo ">>> 检查部署前置条件..."

    if ! command -v docker &> /dev/null; then
        echo "错误: Docker 未安装，请先安装 Docker"
        exit 1
    fi

    if ! docker compose version &> /dev/null; then
        echo "错误: Docker Compose V2 未安装"
        exit 1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        echo "错误: .env 文件不存在"
        echo "请将 .env 文件放到 $PROJECT_DIR/ 目录下"
        exit 1
    fi

    if [ ! -d "$PROJECT_DIR/data" ]; then
        echo "警告: data/ 目录不存在，正在创建..."
        mkdir -p "$PROJECT_DIR/data/knowledge_base" "$PROJECT_DIR/data/sops"
    fi

    echo "前置条件检查通过"
}

# 生成/校验管理端 Basic Auth 密码文件（.htpasswd 不入库，首次自动生成随机密码）
ensure_htpasswd() {
    HTPASSWD_FILE="$SCRIPT_DIR/nginx/.htpasswd"
    if [ -d "$HTPASSWD_FILE" ]; then
        STALE_HTPASSWD="$HTPASSWD_FILE.stale.$(date +%s)"
        echo "!!! $HTPASSWD_FILE 是目录（可能是 Docker 为缺失的挂载源自动创建），正在移开并重新生成: $STALE_HTPASSWD"
        mv "$HTPASSWD_FILE" "$STALE_HTPASSWD"
    fi
    if [ -f "$HTPASSWD_FILE" ]; then
        echo ">>> 管理端密码文件已存在: $HTPASSWD_FILE"
        return
    fi

    ADMIN_USER="${ADMIN_USER:-admin}"
    ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

    if [ -z "$ADMIN_PASSWORD" ] && [ -f "$PROJECT_DIR/.env" ]; then
        ADMIN_PASSWORD=$(grep -E '^ADMIN_PASSWORD=' "$PROJECT_DIR/.env" | head -n1 | cut -d= -f2-)
    fi

    if [ -z "$ADMIN_PASSWORD" ]; then
        ADMIN_PASSWORD=$(openssl rand -hex 8)
        echo "!!! 未设置 ADMIN_PASSWORD，已生成随机密码: $ADMIN_PASSWORD"
        echo "!!! 请保存该密码，并建议写入 $PROJECT_DIR/.env 的 ADMIN_PASSWORD 以便重启后保持"
    fi

    mkdir -p "$SCRIPT_DIR/nginx"
    if command -v htpasswd >/dev/null 2>&1; then
        htpasswd -nb "$ADMIN_USER" "$ADMIN_PASSWORD" > "$HTPASSWD_FILE"
    else
        HASH=$(openssl passwd -apr1 "$ADMIN_PASSWORD")
        printf '%s:%s\n' "$ADMIN_USER" "$HASH" > "$HTPASSWD_FILE"
    fi
    chmod 600 "$HTPASSWD_FILE"
    echo ">>> 已生成管理端密码文件: $HTPASSWD_FILE (用户: $ADMIN_USER)"
}

deploy() {
    echo "=========================================="
    echo "   AnGIneer 部署 (服务器端)"
    echo "=========================================="
    echo "项目目录: $PROJECT_DIR"
    echo "=========================================="

    check_prerequisites
    ensure_htpasswd

    echo ">>> 构建 Docker 镜像..."
    docker compose -f "$COMPOSE_FILE" build

    if [ "$BUILD_ONLY" = true ]; then
        echo ">>> 仅构建模式，跳过启动"
        return
    fi

    echo ">>> 启动服务..."
    docker compose -f "$COMPOSE_FILE" up -d

    echo ">>> 等待服务就绪..."
    sleep 10

    echo ">>> 服务状态:"
    docker compose -f "$COMPOSE_FILE" ps

    echo ""
    echo "=========================================="
    echo "   部署完成！"
    echo "=========================================="
    echo "前端访问:  http://localhost/"
    echo "管理后台:  http://localhost/admin/ (Basic Auth；建议 SSH 隧道访问)"
    echo "API 文档:  http://localhost/api/docs"
    echo "=========================================="
}

prepare_services() {
    check_prerequisites
    ensure_htpasswd
    echo ">>> 部署前置准备完成"
}

stop_services() {
    echo ">>> 停止所有服务..."
    docker compose -f "$COMPOSE_FILE" down
    echo "服务已停止"
}

restart_services() {
    echo ">>> 重启所有服务..."
    docker compose -f "$COMPOSE_FILE" restart
    echo "服务已重启"
}

show_logs() {
    docker compose -f "$COMPOSE_FILE" logs -f
}

show_status() {
    docker compose -f "$COMPOSE_FILE" ps
}

case $ACTION in
    prepare)  prepare_services ;;
    stop)     stop_services ;;
    restart)  restart_services ;;
    logs)     show_logs ;;
    status)   show_status ;;
    deploy)   deploy ;;
esac
