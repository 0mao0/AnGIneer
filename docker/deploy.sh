#!/bin/bash
# AnGIneer 一键部署脚本
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

deploy() {
    echo "=========================================="
    echo "   AnGIneer 部署"
    echo "=========================================="
    echo "项目目录: $PROJECT_DIR"
    echo "=========================================="

    check_prerequisites

    echo ">>> 拉取最新代码..."
    cd "$PROJECT_DIR"
    git pull origin main

    echo ">>> 构建 Docker 镜像（首次较慢，约 5-10 分钟）..."
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
    echo "管理后台:  http://localhost/admin/"
    echo "API 文档:  http://localhost/api/docs"
    echo "=========================================="
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
    stop)     stop_services ;;
    restart)  restart_services ;;
    logs)     show_logs ;;
    status)   show_status ;;
    deploy)   deploy ;;
esac
