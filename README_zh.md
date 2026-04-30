# AI Helix

[English](README.md) | 中文 | [官方网站](https://ai-helix.com) | [文档](https://docs.ai-helix.com)

[![GitHub stars](https://img.shields.io/github/stars/simpleyyt/ai-helix?style=social)](https://github.com/simpleyyt/ai-helix/stargazers)
&ensp;
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AI Helix 是一个通用的 AI Agent 系统，支持在沙盒环境中运行各种工具和操作。

用 AI Helix 开启你的智能体之旅吧！

👏 欢迎加入 [QQ群(1005477581)](https://qun.qq.com/universal-share/share?ac=1&authKey=p4X3Da5iMpR4liAenxwvhs7IValPKiCFtUevRlJouz9qSTSZsMnPJc3hzsJjgQYv&busi_data=eyJncm91cENvZGUiOiIxMDA1NDc3NTgxIiwidG9rZW4iOiJNZmUrTmQ0UzNDZDNqNDFVdjVPS1VCRkJGRWVlV0R3RFJSRVFoZDAwRjFDeUdUM0t6aUIyczlVdzRjV1BYN09IIiwidWluIjoiMzQyMjExODE1In0%3D&data=C3B-E6BlEbailV32co77iXL5vxPIhtD9y_itWLSq50hKqosO_55_isOZym2Faaq4hs9-517tUY8GSWaDwPom-A&svctype=4&tempid=h5_group_info)

❤️ 喜欢 AI Helix? 点亮小星星 🌟 或 [赞助开发者](docs/sponsor.md)! ❤️

🚀 [Demo 演示](https://app.ai-helix.com)

📝 [博客：我也复刻了一个 Helix，带高仿 WebUI 和沙盒](https://simpleyyt.com/2026/03/07/rebuild-helix-with-webui-and-sandbox/)

## 示例

### 基本功能

https://github.com/user-attachments/assets/37060a09-c647-4bcb-920c-959f7fa73ebe

### Browser Use

* 任务：llm 最新论文

https://github.com/user-attachments/assets/8f7788a4-fbda-49f5-b836-949a607c64ac

### Code Use

* 任务：写一个复杂的 python 示例

https://github.com/user-attachments/assets/5cb2240b-0984-4db0-8818-a24f81624b04


## 主要特性

 * 部署：最小只需要一个 LLM 服务即可完成部署，不需要依赖其它外部服务。
 * 工具：支持 Terminal、Browser、File、Web Search、消息工具，并支持实查看和接管，支持外部 MCP 工具集成。
 * 沙盒：每个 Task 会分配单独的一个沙盒，沙盒在本地 Dock 环境里面运行。
 * 任务会话：通过 Postgres/Redis 对会话历史进行管理，支持后台任务。
 * 对话：支持停止与打断，支持文件上传与下载。
 * 多语言：支持中文与英文。
 * 认证：用户登录与认证。

## 开发计划

 * 工具：支持 Deploy & Expose。
 * 沙盒：支持手机与 Windows 电脑接入。
 * 部署：支持 K8s 和 Dock Swarm 多集群部署。

## 环境要求

本项目主要依赖Docker进行开发与部署，需要安装较新版本的Docker：
- Docker 20.10+
- Docker Compose

模型能力要求：
- 支持 LangChain Chat Model（默认 `openai` 提供商）
- 支持FunctionCall
- 支持Json Format输出

推荐使用Deepseek与GPT模型。


## 部署指南

推荐使用Docker Compose进行部署：

<!-- docker-compose-example.yml -->
```yaml
services:
  frontend:
    image: simpleyyt/helix-frontend
    ports:
      - "5173:80"
    depends_on:
      - backend
    restart: unless-stopped
    networks:
      - helix-network
    environment:
      - BACKEND_URL=http://backend:8000

  backend:
    image: simpleyyt/helix-backend
    depends_on:
      - sandbox
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      #- ./mcp.json:/etc/mcp.json # Mount MCP servers directory
    networks:
      - helix-network
    environment:
      # Anthropic API key(若 AGENT_LLM_BASE_URL 指向自带鉴权的网关则可留空)
      - LLM_API_KEY=
      # 可选:私有网关 / 出站代理,默认直连上游
      #- AGENT_LLM_BASE_URL=
      #- LLM_PROXY_ADDRESS=
      # LLM 模型名
      - MODEL_NAME=claude-sonnet-4-5
      # LLM 温度，控制随机性
      #- TEMPERATURE=0.7
      # 最大输出 tokens
      #- MAX_TOKENS=4096
      # 更多配置：https://docs.ai-helix.com/#/configuration

  sandbox:
    image: simpleyyt/helix-sandbox
    command: /bin/sh -c "exit 0"  # prevent sandbox from starting, ensure image is pulled
    restart: "no"
    networks:
      - helix-network

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=helix
      - POSTGRES_PASSWORD=helix
      - POSTGRES_DB=helix
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - helix-network

  redis:
    image: redis:7.0
    restart: unless-stopped
    networks:
      - helix-network

volumes:
  postgres_data:
    name: helix-postgres-data

networks:
  helix-network:
    name: helix-network
    driver: bridge
```
<!-- /docker-compose-example.yml -->

保存成`docker-compose.yml`文件，并运行

```shell
docker compose up -d
```

> 注意：如果提示`sandbox-1 exited with code 0`，这是正常的，这是为了让 sandbox 镜像成功拉取到本地。

打开浏览器访问<http://localhost:5173>即可访问 Helix。更多配置见：https://docs.ai-helix.com/#/configuration

## 开发指南

### 项目结构

本项目由以下子项目组成：

* `ui/www`: Helix React 前端
* `backend`: Helix 后端
* `sandbox`: Helix 沙盒
* `mockserver`: 模拟 LLM 服务（开发/测试用）

### 整体设计

![Image](https://github.com/user-attachments/assets/69775011-1eb7-452f-adaf-cd6603a4dde5)

**当用户发起对话时：**

1. Web 向 Server 发送创建 Agent 请求，Server 通过`/var/run/docker.sock`创建出 Sandbox，并返回会话 ID。
2. Sandbox 是一个 Ubuntu Docker 环境，里面会启动 chrome 浏览器及 File/Shell 等工具的 API 服务。
3. Web 往会话 ID 中发送用户消息，Server 收到用户消息后，将消息发送给 PlanAct Agent 处理。
4. PlanAct Agent 处理过程中会调用相关工具完成任务。
5. Agent 处理过程中产生的所有事件通过 SSE 发回 Web。

**当用户浏览工具时：**

- 浏览器：
    1. Sandbox 的无头浏览器通过 xvfb 与 x11vnc 启动了 vnc 服务，并且通过 websockify 将 vnc 转化成 websocket。
    2. Web 的 NoVNC 组件通过 Server 的 Websocket Forward 转发到 Sandbox，实现浏览器查看。
- 其它工具：其它工具原理也是差不多。

### 环境准备

1. 下载项目：
```bash
git clone https://github.com/simpleyyt/ai-helix.git
cd ai-helix
```

2. 复制配置文件：
```bash
cp .env.example .env
```

3. 按需修改配置文件,把 `LLM_API_KEY` 设成你的 Anthropic API key,完整配置项见 [.env.example](https://github.com/simpleyyt/ai-helix/blob/main/.env.example) 或[配置说明](https://docs.ai-helix.com/#/configuration):

```ini
MODEL_NAME=claude-sonnet-4-5
LLM_API_KEY=sk-ant-...
# 可选:私有网关 / 出站代理
#AGENT_LLM_BASE_URL=
#LLM_PROXY_ADDRESS=
```

### 开发调试

1. 运行调试：
```bash
# 相当于 docker compose -f docker-compose-development.yaml up
./dev.sh up
```

各服务会以 reload 模式运行，代码改动会自动重新加载。暴露的端口如下：
- 5173: Web前端端口
- 8000: Server API服务端口
- 8080: Sandbox API服务端口
- 5900: Sandbox VNC端口
- 9222: Sandbox Chrome浏览器CDP端口

> *注意：在 Debug 模式全局只会启动一个沙盒*

2. 当依赖变化时（`backend/pyproject.toml` 或 `ui/www/package.json`），清理并重新构建：
```bash
# 清理所有相关资源
./dev.sh down -v

# 重新构建镜像
./dev.sh build

# 调试运行
./dev.sh up
```

### 镜像发布

```bash
export IMAGE_REGISTRY=your-registry-url
export IMAGE_TAG=latest

# 构建镜像
./run build

# 推送到相应的镜像仓库
./run push
```

## ⭐️ Star 记录

[![Star History Chart](https://api.star-history.com/svg?repos=Simpleyyt/ai-helix&type=Date)](https://www.star-history.com/#Simpleyyt/ai-helix&Date)
