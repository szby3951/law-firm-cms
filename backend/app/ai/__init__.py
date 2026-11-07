"""模块9 的模型接入层。

- :mod:`app.ai.gateway`：业务代码唯一入口（对话 / JSON / 向量化），使用说明见 ``README.md``
- :mod:`app.ai.llm_clients`：大模型客户端与供应商注册表
- :mod:`app.ai.embedding`：本地 TEI 向量服务客户端

这里故意不做聚合导入：``app.ai`` 会被路由层间接 import，若在包初始化时构造客户端，
会拖慢启动，也会在配置缺失时让整个应用起不来。
"""
