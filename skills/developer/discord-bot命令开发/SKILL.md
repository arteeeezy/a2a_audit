---
name: discord-bot命令开发
description: Discord Bot命令开发
---

# Discord Bot命令开发

必须使用async/await异步语法；参数验证应在业务逻辑前完成；错误提示应清晰友好；所有用户交互通过ctx.send()进行；考虑添加异常处理机制


## Steps

1. 使用@bot.command()装饰器定义命令函数
2. 在函数开始处验证输入参数的有效性
3. 实现核心业务逻辑处理
4. 使用await ctx.send()返回处理结果或错误提示


## Template

```
@bot.command()
async def command_name(ctx, *args):
    # 参数验证
    if not args:
        await ctx.send("错误提示信息")
        return
    
    # 业务逻辑处理
    result = process_logic(args)
    
    # 返回结果
    await ctx.send(f"结果：{result}")
```
