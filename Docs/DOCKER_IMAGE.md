# 预构建镜像

`.github/workflows/docker-image.yml` 在 `master` 的源码变化时构建
`deploy/docker/Dockerfile`，推送到 GitHub Container Registry。镜像里只有
`DNF90Server` 与 `DNF90Assets` 两个静态二进制，配置、PVF、频道表、数据库和
日志全部在挂载目录里。

## 拉取

```sh
docker pull ghcr.io/oyxp233/servers5a3:latest
```

镜像名由工作流的 `env.IMAGE_NAME` 决定，所属账号取仓库 owner。要换名字只改
`docker-image.yml` 里那一行。

## 标签

| 标签 | 产生时机 | 用途 |
| --- | --- | --- |
| `latest` | `master` 每次构建 | 跟最新源码 |
| `sha-<7位>` | 每次构建 | 精确回到某次提交 |
| `YYYYMMDD` | `master` 当天首次构建 | 按日期回滚 |
| `1.2.3`、`1.2` | 推送 `v1.2.3` 标签 | 版本化 |

`latest` 与日期标签会被后来的构建覆盖；`sha-` 前缀的不会，它唯一对应一个提交，
回滚时优先用它。

## 用镜像部署

`deploy/docker/manage.py` 默认用本地构建的 `servers5a3-local:dev`。改用预构建
镜像有两种写法，效果相同：

```sh
# 命令行
python deploy/docker/manage.py --image ghcr.io/oyxp233/servers5a3:latest prepare
```

```json
// runtime/config/instance.json
"server_image": "ghcr.io/oyxp233/servers5a3:latest"
```

改完照常 `prepare`、`up`。`generate()` 把 `server_image` 写进生成的
`compose.json`，所以只改配置不需要重新构建。

私有仓库的镜像需要先登录，否则拉取会 401：

```sh
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <你的账号> --password-stdin
```

## 镜像边界

| 内容 | 在哪 |
| --- | --- |
| 服务端二进制 | 镜像内 `/usr/local/bin` |
| 实例配置、存档 | 挂载 `./server` → `/runtime` |
| PVF、频道表 | 挂载 `./data` → `/runtime/data/dnf` |
| 数据库 | 独立的 `mariadb` 服务 |
| 日志 | 挂载目录内，同时走 docker json-file 轮转 |

换镜像不会带走存档：数据库在 `database` 卷里，实例文件在宿主机目录里。回滚
只需要把 `server_image` 指回旧的 `sha-` 标签再 `up`。

## 目录权限

容器以 `uid/gid 10001` 运行（`deploy/docker/Dockerfile` 里写死）。镜像内的
`/runtime` 属主是 root，所以**必须**挂载宿主机目录覆盖它，且该目录要让 10001
可写：

```sh
sudo chown -R 10001:10001 runtime/server
```

`manage.py` 在 Linux 上以当前用户身份创建 `./server`，若当前用户不是 10001，
容器启动后会因无法写配置而退出。Windows 上 Docker Desktop 的挂载会做权限映射，
通常不需要处理。

## 本地构建

```sh
docker build -t servers5a3-local:dev -f deploy/docker/Dockerfile .
```

国内网络拉不到 `docker.io` 时，可以从镜像站拉同 digest 的基础镜像再打回官方
名字，构建会命中本地缓存：

```sh
docker pull docker.m.daocloud.io/library/golang:1.26.5-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2
docker tag docker.m.daocloud.io/library/golang@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 golang:1.26.5-alpine
docker build --pull=false -t servers5a3-local:dev -f deploy/docker/Dockerfile .
```

基础镜像用 digest 固定，镜像站与官方是同一份内容，tag 后 digest 不变。

## 不做什么

- 不跑测试。`verify.yml` 已有完整验证，构建流水线只负责出镜像。
- 不打多架构。当前只出 `linux/amd64`，ARM 机器需要自己加 `platforms`。
- 不自动部署。镜像推上去就结束，什么时候 `up` 由人决定。
