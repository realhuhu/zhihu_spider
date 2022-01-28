import re
import json
import asyncio
from hashlib import md5
from urllib.parse import urlencode, urlsplit, parse_qs

import aiohttp


class ZhiHu:
    articles_api = "https://www.zhihu.com/api/v4/search_v3"
    comments_api = "https://www.zhihu.com/api/v4/%s/%s/root_comments?order=normal&limit=20&offset=0&status=open"
    children_comments_api = "https://www.zhihu.com/api/v4/comments/%s/child_comments"
    encrypt_api = "https://service-denf06ck-1253616191.gz.apigw.tencentcs.com/release/secret/"

    def __init__(self, query, client):
        self.client = client
        self.query = query
        self.offset = 0
        self.article_id_list = []

    async def encrypt(self, params):
        raw = f'101_3_2.0+/api/v4/search_v3?{urlencode(params)}+"AIAd0x-RZROPTgLVVevqLR6wbdu2E2cngB8=|1626013553"'
        s = md5(raw.encode("utf-8")).hexdigest()
        async with self.client.get(self.encrypt_api + s) as res:
            return await res.text()

    async def get_articles(self):
        params = {
            "t": "general",
            "q": self.query,
            "correction": 1,
            "offset": self.offset,
            "limit": 20,
            "filter_fields": "",
            "lc_idx": self.offset,
            "show_all_topics": 0,
            "search_source": "Normal",
        }
        async with self.client.get(self.articles_api, params=params, headers={
            "x-zse-96": "2.0_" + await self.encrypt(params)
        }) as res:
            result = await res.json()
            if result.get("error"):
                return None
            self.offset = parse_qs(urlsplit(result["paging"]["next"]).query)["offset"][0]
            return self.parse_articles(result)

    @staticmethod
    def simplify(s):
        if s:
            return re.sub("<.*?>", "", s)

    def parse_articles(self, raw):
        articles = []
        for article in raw["data"]:
            if article["type"] not in ["zvideo", "search_result"]:
                continue

            article_id = article["object"].get("id") or article["object"].get("zvideo_id")
            if article_id in self.article_id_list:
                continue

            article_type = article["object"]["type"]
            if article_type not in ["article", "answer", "zvideo"]:
                continue

            self.article_id_list.append(article_id)
            articles.append({
                "type": article_type,
                "id": article_id,
                "title": self.simplify(article['highlight']['title'])
            })
        return {
            "is_end": raw["paging"]["is_end"],
            "articles": articles
        }

    async def get_children_comments(self, root_comment):
        comments = []
        root_id = root_comment["id"]
        url = self.children_comments_api % root_id
        while True:
            async with self.client.get(url) as res:
                raw = await res.json()
                for comment in raw["data"]:
                    if not comment["type"] == "comment":
                        continue
                    comments.append({
                        "id": comment["id"],
                        "content": self.simplify(comment["content"])
                    })
                if raw["paging"]["next"]:
                    break
        return {
            "id": root_comment["id"],
            "content": self.simplify(root_comment["content"]),
            "children_comments": comments
        }

    async def get_root_comments(self, raw):
        comments = []
        if raw_data := list(filter(lambda x: x["type"] == "comment", raw["data"])):
            done, _ = await asyncio.wait(
                map(lambda x: asyncio.create_task(self.get_children_comments(x), name=x["id"]), raw_data),
                timeout=10
            )
            comments += map(lambda x: x.result(), done)
        return {
            "is_end": raw["paging"]["is_end"],
            "comments": comments
        }

    async def get_comments(self, article):
        comments = []
        article_type = article["type"]
        article_id = article['id']
        url = self.comments_api % (article_type + "s", article_id)
        while True:
            async with self.client.get(url) as res:
                raw = await res.json()
                result = await self.get_root_comments(raw)
                comments += result["comments"]
                url = raw["paging"]["next"]
                if result["is_end"]:
                    break
        return {
            "id": article_id,
            "title": article["title"],
            "comments": comments
        }

    @classmethod
    async def run(cls, query, save_to=None, auto=False):
        async with aiohttp.ClientSession(headers={
            "x-api-version": "3.0.91",
            "x-zse-93": "101_3_2.0",
            "User-Agent": "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; TencentTraveler 4.0)",
            "cookie": 'd_c0="AIAd0x-RZROPTgLVVevqLR6wbdu2E2cngB8=|1626013553"',
        }) as client:
            cli = cls(query, client)
            data = []
            while auto or input("按换行继续，其它键停止并保存数据>>>:") == "":
                res = await cli.get_articles()
                if res["articles"]:
                    done, _ = await asyncio.wait(
                        map(lambda x: asyncio.create_task(cli.get_comments(x), name=x['id']), res["articles"]),
                        timeout=10
                    )
                    data += map(lambda x: x.result(), done)
                    for i in data:
                        print(i["title"])
                if res["is_end"]:
                    print("没有了")
                    break
            with open(save_to or "output1.json", "w") as f:
                json.dump(data, f)


if __name__ == '__main__':
    query = input("请输入搜索词>>>:")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(ZhiHu.run(query=query, auto=True))
