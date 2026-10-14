from emotion_engine import analyze_context
from sticker_engine import search_sticker


texts = [

"实验失败了，好难受，抱抱我",

"宝宝我终于买到域名啦",

"今天真的好开心"

]


for text in texts:

    print("\n用户:")
    print(text)

    context = analyze_context(text)

    print("\n分析:")
    print(context)

    result = search_sticker(context)

    print("\n猫猫:")
    
    if result:
        print(result["name"])
    else:
        print("没有找到")
