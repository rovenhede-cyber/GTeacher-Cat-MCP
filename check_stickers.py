import requests

from sticker_engine import load_library


IMAGE_BASE_URL = (
    "https://raw.githubusercontent.com/"
    "rovenhede-cyber/stickersforGPT/main/"
)



def check_stickers():

    print("\n🐱 GTeacher Cat 猫猫质检系统启动\n")


    # 加载 GitHub 最新数据

    data = load_library()


    stickers = data.get(
        "stickers",
        []
    )


    print(
        f"📦 当前猫猫数量: {len(stickers)}\n"
    )


    used_files = set()

    used_ids = set()


    error_count = 0



    for cat in stickers:


        print("=" * 50)


        cat_id = cat.get(
            "id",
            ""
        )

        name = cat.get(
            "name",
            "未命名猫"
        )

        file = cat.get(
            "file",
            ""
        )

        description = cat.get(
            "description",
            ""
        )

        tags = cat.get(
            "tags",
            []
        )

        use_when = cat.get(
            "use_when",
            []
        )


        print(
            f"🐱 {name}"
        )

        print(
            f"🆔 ID: {cat_id}"
        )

        print(
            f"🖼 图片: {file}"
        )


        # -------------------------
        # 1. ID检查
        # -------------------------

        if not cat_id:

            print(
                "❌ 缺少ID"
            )

            error_count += 1


        elif cat_id in used_ids:

            print(
                "❌ ID重复:",
                cat_id
            )

            error_count += 1


        else:

            used_ids.add(
                cat_id
            )



        # -------------------------
        # 2. 图片路径检查
        # -------------------------

        if not file:

            print(
                "❌ 没有图片路径"
            )

            error_count += 1


        elif file in used_files:

            print(
                "⚠️ 图片路径重复:",
                file
            )

            error_count += 1


        else:

            used_files.add(
                file
            )



        # -------------------------
        # 3. 描述检查
        # -------------------------

        if not description:

            print(
                "❌ 缺少图片描述"
            )

            error_count += 1


        else:

            print(
                "✅ 描述存在"
            )



        # -------------------------
        # 4. 标签检查
        # -------------------------

        if not tags:

            print(
                "⚠️ 没有tags"
            )


        else:

            print(
                "🏷 标签:",
                ", ".join(tags)
            )



        # -------------------------
        # 5. 使用场景检查
        # -------------------------

        if not use_when:

            print(
                "⚠️ 没有use_when"
            )



        # -------------------------
        # 6. GitHub图片检查
        # -------------------------

        if file:


            url = IMAGE_BASE_URL + file


            try:

                response = requests.head(
                    url,
                    timeout=10
                )


                if response.status_code == 200:

                    print(
                        "✅ 图片链接正常"
                    )


                else:

                    print(
                        "❌ 图片不存在:",
                        response.status_code
                    )

                    error_count += 1



            except Exception as e:

                print(
                    "❌ 图片检查失败:",
                    e
                )

                error_count += 1




    print("\n" + "=" * 50)


    if error_count == 0:

        print(
            "🎉 质检通过！所有猫猫状态良好！"
        )


    else:

        print(
            f"⚠️ 发现 {error_count} 个问题，请检查"
        )


    print(
        "\n🐾 GTeacher Cat 检查结束\n"
    )



if __name__ == "__main__":

    check_stickers()