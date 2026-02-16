
import aiohttp
import asyncio
import ssl

async def test_net():
    url = "https://api.upbit.com/v1/market/all"
    
    print("1. Standard Request:")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                print(f"Status: {resp.status}")
    except Exception as e:
        print(f"Failed: {type(e)} {e}")

    print("\n2. No SSL Verify:")
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, ssl=ctx) as resp:
                print(f"Status: {resp.status}")
    except Exception as e:
        print(f"Failed: {type(e)} {e}")

if __name__ == "__main__":
    asyncio.run(test_net())
