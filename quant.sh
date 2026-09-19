#!/bin/bash
# A股量化选股系统 - 快捷命令脚本

QUANT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"

cd "$QUANT_DIR" || exit 1

case "$1" in
    init|update|run|track|backtest|web)
        "$PYTHON" main.py "$@"
        ;;
    *)
        echo "使用方法: $0 {init|update|run|track|backtest|web}"
        echo ""
        echo "命令说明:"
        echo "  init     - 首次全量抓取6年历史数据"
        echo "  update   - 每日增量更新"
        echo "  run      - 完整流程（更新+选股+通知）"
        echo "  track    - 回填并查看历史战绩"
        echo "  backtest - 运行历史回测"
        echo "  web      - 启动 Web 服务与调度器"
        exit 1
        ;;
esac
