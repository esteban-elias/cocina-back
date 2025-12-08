import asyncio
import subprocess
import time
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

# List of URLs to crawl
urls = [
    "https://www.jumbo.cl/frutas-y-verduras",
    "https://www.jumbo.cl/lacteos-y-quesos",
    "https://www.jumbo.cl/despensa",
    "https://www.jumbo.cl/carnes-y-pescados",
]

crawler_conf = CrawlerRunConfig(
    wait_for="css:.shelf-content"
)

async def main():
    for url in urls:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(
                url=url,
                config=crawler_conf
            )

        if (result is None):
            raise ValueError("Crawl failed")

        category = url.split('/')[-1]
        
        with open(f"data/{category}.md", "w", encoding="utf-8") as f:
            f.write(result.markdown)
        
        time.sleep(3)

if __name__ == '__main__':
    asyncio.run(main())

