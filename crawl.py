import asyncio
import subprocess
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

# List of URLs to crawl
urls = [
    "https://www.jumbo.cl/frutas-y-verduras",
    "https://www.jumbo.cl/lacteos-y-quesos",
    "https://www.jumbo.cl/despensa",
    "https://www.jumbo.cl/carnes-y-pescados",
    "https://www.jumbo.cl/panaderia-y-pasteleria",
    "https://www.jumbo.cl/licores-bebidas-y-aguas",
    "https://www.jumbo.cl/chocolates-galletas-y-snacks"
]

crawler_conf = CrawlerRunConfig(
    wait_for="css:.shelf-content"
)

async def main():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://www.jumbo.cl/frutas-y-verduras",
            config=crawler_conf
        )

    if (result is None):
        raise ValueError("Crawl failed")
    
    with open("data/frutas-y-verduras.md", "w", encoding="utf-8") as f:
        f.write(result.markdown)

if __name__ == '__main__':
    asyncio.run(main())

