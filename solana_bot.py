import requests
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.client import Token

async def get_token_metadata(client, token_address: str):
    
    token_pubkey = Pubkey.from_string(token_address)
    
    # Initialize a Token Object
    token = Token(client, token_pubkey, TOKEN_PROGRAM_ID, None)
    mint_info = await token.get_mint_info()
    token_accounts = await client.get_token_accounts_by_owner(token_pubkey, token_program_id=TOKEN_PROGRAM_ID, commitment=Confirmed)
    
    if not token_accounts['result']['value']:
        return None
    
    account_info = token_accounts['result']['value'][0]['account']['data']['parsed']['info']
    
    return {
        'name': account_info.get('name', 'unknowm'),
        'symbol': account_info.get('symbol', 'unknown'),
        'decimals': mint_info.decimals,
        'supply': mint_info.supply
    }

def get_token_details_dexscreener(token_address: str):

    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        
        if 'pairs' in data:
            pair_data = data['pairs'][0]
            return {
                'exchange': ['dexId'],
                'market_cap': pair_data['fdv'],
                'liquidity': pair_data['liquidity']['usd'],
                'token_price': pair_data['priceUsd']
            }
    
    return None

