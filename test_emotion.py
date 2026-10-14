from emotion_engine import analyze_context


texts = [

"实验失败了，好难受，抱抱我",

"宝宝我终于买到域名啦",

"这个代码怎么优化"

]


for t in texts:

    print("\n输入:")
    print(t)

    print(
        analyze_context(t)
    )