# GitGud 权威源码与 GitHub 单向镜像

GitGud 上游主干是唯一权威源码。独立功能、修复、测试、文档和 CI 分支均通过 MR 汇入上游；GitHub 只镜像上游的确切提交，不作为另一条开发主干。GitGud fork 仅用于承载贡献分支。

## Agent 工作流

1. 拉取实际上游主干，核对已有 MR；同一事项更新原 MR，不重复创建。
2. 在干净的独立工作树审查精确差异。将分支推到 GitGud fork，创建面向上游 master 的中文 MR，说明行为、验证、依赖和待实机验收项。已提交并准备集成的分支不能仅推到 fork 就视为完成贡献。
3. 出现冲突时由负责同步的 Agent 合入最新上游，逐项保留双方有效逻辑，验证后非强推更新原分支。不得用整文件覆盖、强推或丢弃既有修复来消除冲突。
4. 按用户已有授权和项目评审要求合并 MR，核对最终上游 SHA。草稿、研究与未验证候选在 MR 中明确状态，不因成功推送而称已合并。
5. GitHub Actions 把上游提交并进 GitHub 主干并读回两侧 SHA。上游领先时快进；镜像自带 CI 提交时产生一个合并提交（见[镜像自带的 CI 定义](#镜像自带的-ci-定义)）。不创建同步 PR、不把 GitHub 独有改动回推上游。
6. 部署从实际 active 累计基线保留已上线功能与私有扩展，独立完成资源门槛、测试、备份、切换及运行读回。源码 MR、上游合并、镜像成功和游戏部署分别记录。

CI 与同步脚本的变更同样在上游 MR 审查，合并后正常镜像。镜像进程只执行当前已检出的脚本，不执行本次抓取的代码。

## GitHub 配置

本仓库的同步不需要任何密钥，开箱即用：

- 上游默认是 GitHub 镜像 `https://github.com/Cec1c/ServerS5A3.git`。要换回 GitGud 原始上游或别的公开仓库，配仓库变量 `UPSTREAM_REPOSITORY` 覆盖即可；不配就用默认值。
- 认证只用内置 `GITHUB_TOKEN`：fetch 上游是匿名 HTTPS，push 本仓库用 token 的 extraheader。**不需要 Deploy Key，不需要 SSH Secret**。
- 工作流声明 `contents: write`（推主干）和 `actions: write`（触发镜像构建）。主干若开了保护规则，要允许 `GITHUB_TOKEN` 推送——快进与合并提交都要放行，只允许快进会让带 CI 提交的镜像同步失败。
- Repository sync 每小时第 7 分钟计划运行（`7 * * * *`），保留手动触发；调度可能延迟。相同 SHA 不写入。
- **`GITHUB_TOKEN` 推送不会触发 `push` 事件**，所以同步工作流在 `applied=true` 时会显式调用 `gh workflow run docker-image.yml`。少了这一步，同步进来的上游更新不会出镜像。
- 早期版本的 `GITGUD_UPSTREAM_REPOSITORY` 变量、`SOURCE_MIRROR_SSH_KEY` / `SOURCE_MIRROR_KNOWN_HOSTS` 密钥已不再使用，可以删除。

| 主干关系 | 动作 |
| --- | --- |
| 相同 SHA | 不写入 |
| GitHub 是上游的祖先 | GitHub 非强推快进到上游确切 SHA |
| GitHub 独自领先（上游无新提交） | 不写入，报告 `github-ahead` |
| 双方分叉（镜像带 CI 提交） | 合并上游进镜像，产生一个合并提交 |
| 合并冲突 | 停止；两侧都不写入，需人工处理 |
| 抓取后任一引用变化 | 重新读取再执行；不覆盖中途提交 |

不强推、不删除分支、不移动标签。源码镜像不修改 Release、Issue、MR、设置、密钥、玩家资源或线上服务。客户端 EXE Release 仍按独立批准的流程执行，见 Docs/CLIENT_RELEASE_SYNC.md；本次源码权威迁移不调整其资产规则。

## 镜像自带的 CI 定义

本仓库（`oyxp233/servers5a3-docker`）在镜像之外还维护两个上游没有的工作流：

| 文件 | 作用 |
| --- | --- |
| `.github/workflows/docker-image.yml` | 源码变化时构建并推送 `ghcr.io` 镜像 |
| `.github/workflows/repository-sync.yml` | 每小时把上游并进 master，必要时触发镜像构建 |

同步源默认取 GitHub 镜像 `Cec1c/ServerS5A3` 而不是 GitGud 原始上游：两者内容同步，
而 GitHub 仓库可以直接匿名 HTTPS 拉取，省掉 Deploy Key 与主机密钥。GitGud 仍是
源码权威，这里只是换了一个更省事的读取入口。

这偏离了"不产生镜像合并提交"的原始约定，是有意选择：镜像要能自动出镜像，就必须
有一份上游不存在的 workflow 文件，而任何 GitHub 独有的提交都会让纯快进同步失败。

代价与边界：

- 上游领先时仍然快进，只有镜像确实带提交时才产生合并提交。合并提交的消息固定为
  `Merge authoritative upstream <sha> into master`，便于审计。
- 合并冲突不自动解决。冲突时工作流失败、两侧都不写，需要人工处理。最常见的冲突点
  是上游改动了 `repository-sync.yml` 或 `scripts/ci/sync_repositories.py`。
- 这些改动只存在于 GitHub 镜像，不回推 GitGud。上游若实现同类能力，合并时以上游为准，
  删掉本地的重复实现。
- 镜像构建见[预构建镜像](DOCKER_IMAGE.md)。

## 从多主干迁移

先保存两端精确 SHA，并暂停旧双向同步与 GitHub 自动合并工作流。审查 GitHub 独有提交，通过上游 MR 保留需继承的历史与功能。上游合并后必须成为现有 GitHub 主干的后继，再以非强推引导 GitHub 到该上游提交；不 reset 或覆盖历史。配置专用镜像凭据，启用单向工作流并验证一次真实运行及相同版本无写入。

没有 Runner 的贡献 fork 可关闭自身 CI/CD；不因此关闭原作者 CI。Verify 保持手动入口；源码镜像自动构建容器镜像，但不部署游戏。

## 本地验证

```text
python -m unittest discover -s scripts/ci -p "test_*.py" -v
python scripts/ci/sync_repositories.py --github <GitHub镜像URL> --upstream <GitGud权威URL>
```

默认 dry run；--apply 仅写 GitHub。回归覆盖相等、快进、GitHub领先、分叉、上游移动、并发写入拒绝、CI文件同步与抓取脚本不执行。输出不包含凭据或提供者原始错误。
