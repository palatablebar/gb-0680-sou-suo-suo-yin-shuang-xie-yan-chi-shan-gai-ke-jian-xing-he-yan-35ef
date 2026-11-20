# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存，parameters.tenant_scope可声明切换租户范围（列表，空或缺省按输入推导；提交前规范化，乱序重跑仍同批）。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV，首行之后为tenant_scope行（声明范围与结论范围），accepted与quarantine行均带tenant_id。
