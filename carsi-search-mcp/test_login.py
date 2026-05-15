"""Quick test: CARSI login to Zhizhen via Playwright."""
import asyncio
import sys
sys.path.insert(0, ".")

from carsi_search.carsi import login_to_database

async def main():
    username = input("学号: ").strip()
    password = input("密码: ").strip()

    print(f"\nLogging into zhizhen via CARSI...\n")
    result = await login_to_database("zhizhen", username, password, headless=False)

    if result["success"]:
        print(f"\n✅ SUCCESS: {result['message']}")
        page = result["page"]
        print(f"   Current URL: {page.url}")

        print("\nSearching for '测试'...")
        from carsi_search.databases.zhizhen import ZhizhenAdapter
        adapter = ZhizhenAdapter(page)
        search_result = await adapter.search("测试", page_size=3)

        if search_result.get("success"):
            papers = search_result.get("papers", [])
            print(f"   Found {len(papers)} papers (total: {search_result.get('total', '?')})")
            for p in papers:
                print(f"   - {p.get('title', '?')}")
        else:
            print(f"   Search failed: {search_result.get('error')}")

        await result["auth"].stop()
    else:
        print(f"\n[FAILED] {result['error']}")
        if "auth" in result:
            await result["auth"].stop()

if __name__ == "__main__":
    asyncio.run(main())
