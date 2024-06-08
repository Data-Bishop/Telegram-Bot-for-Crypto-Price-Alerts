from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext, Filters
from telegram import update, ParseMode
from telegram import chat
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.rpc.requests import GetTokenLargestAccounts
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import struct
import base58
import asyncio
from dotenv import load_dotenv
import os
import logging

load_dotenv()

# Implement logger
logging.basicConfig(
    filename='extract.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s'
)

TELEGRAM_BOT_TOKEN = "7276720313:AAF2h0186K5OU7mc0y9Q2S08fITsFuaAIx4"
metadata_program_id = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
MONGO_CONNECTION_STRING = os.getenv('DB_CONNECTION_STRING')

# Initialize MongoDB client
mongo_client = MongoClient(MONGO_CONNECTION_STRING)
db = mongo_client['solana_bot']
alerts_collection = db['alerts']

"""
async def get_token_info_by_metaplex(token_address):
  try:
    # Replace with your actual token address
    mint = await metaplex.tokens().find_mint_by_address(token_address)
    return {
        'name': mint.data.name,
        'symbol': mint.data.symbol,
    }
  except Exception as e:
    print(f"Error fetching token info: {e}")
    return None
"""

def format_number(number: int):
    if number >= 1_000_000_000_000:
        return f"${number / 1_000_000_000_000:.2f}T"
    elif number >= 1_000_000_000:
        return f"${number / 1_000_000_000:.2f}B"
    elif number >= 1_000_000:
        return f"${number / 1_000_000:.2f}M"
    elif number >= 1_000:
        return f"${number / 1_000:.2f}K"
    else:
        return f"${number:.2f}"


def get_metadata_pda(token_address: str):
    metadata_seeds = [
        b"metadata",
        bytes(Pubkey.from_string(metadata_program_id)),
        bytes(Pubkey.from_string(token_address))
    ]
    metadata_pda = Pubkey.find_program_address(metadata_seeds, Pubkey.from_string(metadata_program_id))[0]
    return metadata_pda

def unpack_metadata_account(data: dict):
    assert(data[0] == 4)
    i = 1
    source_account = base58.b58encode(bytes(struct.unpack('<' + "B"*32, data[i:i+32])))
    i += 32
    mint_account = base58.b58encode(bytes(struct.unpack('<' + "B"*32, data[i:i+32])))
    i += 32
    name_len = struct.unpack('<I', data[i:i+4])[0]
    i += 4
    name = struct.unpack('<' + "B"*name_len, data[i:i+name_len])
    i += name_len
    symbol_len = struct.unpack('<I', data[i:i+4])[0]
    i += 4 
    symbol = struct.unpack('<' + "B"*symbol_len, data[i:i+symbol_len])
    i += symbol_len
    uri_len = struct.unpack('<I', data[i:i+4])[0]
    i += 4 
    uri = struct.unpack('<' + "B"*uri_len, data[i:i+uri_len])
    i += uri_len
    fee = struct.unpack('<h', data[i:i+2])[0]
    i += 2
    has_creator = data[i] 
    i += 1
    creators = []
    verified = []
    share = []
    if has_creator:
        creator_len = struct.unpack('<I', data[i:i+4])[0]
        i += 4
        for _ in range(creator_len):
            creator = base58.b58encode(bytes(struct.unpack('<' + "B"*32, data[i:i+32])))
            creators.append(creator)
            i += 32
            verified.append(data[i])
            i += 1
            share.append(data[i])
            i += 1
    primary_sale_happened = bool(data[i])
    i += 1
    is_mutable = bool(data[i])
    metadata = {
        "update_authority": source_account,
        "mint": mint_account,
        "data": {
            "name": bytes(name).decode("utf-8").strip("\x00"),
            "symbol": bytes(symbol).decode("utf-8").strip("\x00"),
            "uri": bytes(uri).decode("utf-8").strip("\x00"),
            "seller_fee_basis_points": fee,
            "creators": creators,
            "verified": verified,
            "share": share,
        },
        "primary_sale_happened": primary_sale_happened,
        "is_mutable": is_mutable,
    }
    return metadata

def get_metadata(metadata_key: Pubkey):
    client = Client("https://api.mainnet-beta.solana.com")
    result = client.get_account_info(get_metadata_pda(metadata_key))
    data = result.value.data
    return(unpack_metadata_account(data))

def get_token_details_dexscreener(token_address: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        
        if 'pairs' in data:
            pair_data = data['pairs'][0]
            return {
                'exchange': pair_data['dexId'],
                'market_cap': pair_data['fdv'],
                'liquidity': pair_data['liquidity']['usd'],
                'token_price': pair_data['priceUsd']
            }
        else:
            return None
    
def get_token_socials(token_address: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
           
        if 'pairs' in data:
            token_info = data['pairs'][0].get('info', {})
            socials = token_info.get('socials', [])
            websites = token_info.get('websites', [])
            image = token_info.get('imageUrl', None)
            chart = data['pairs'][0].get('url', None)
            base_token = data['pairs'][0].get('baseToken', None)
            return socials, websites, image, chart, base_token
        else:
            return None, None, None, None, None

def fetch_description_from_uri(token_address: str):
    metadata = get_metadata(token_address)
    
    uri = metadata['data']['uri']
    response = requests.get(uri)
    if response.status_code == 200:
        data = response.json()
        return data['description']
    else:
        return None

def token_details(token_address: str):
    #async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
            # token_metadata = await get_token_metadata(client, token_address)
            
    token_metadata = get_metadata(token_address)
    token_details = get_token_details_dexscreener(token_address)
    token_socials, token_websites, token_image, token_chart, base_token = get_token_socials(token_address)
    token_description = fetch_description_from_uri(token_address)
    
    if token_details and token_metadata and (token_socials or token_websites or token_image or token_chart or base_token or token_description):
        
        social_links = []
        for social in token_socials:
            if social['type'] == 'twitter':
                social_links.append(f'<a href="{social["url"]}" target="_blank">Twitter</a>🌐')
            elif social['type'] == 'telegram':
                social_links.append(f'<a href="{social["url"]}" target="_blank">Telegram</a>🌐')
        
        for website in token_websites:
            if website['label'] == 'Website':
                social_links.append(f'<a href="{website["url"]}" target="_blank">Website</a>🌐')
        
        if token_chart:
            social_links.append(f'<a href="{token_chart}" target="_blank">Chart</a>📈')

        social_links_str = " | ".join(social_links)
        message = (
                    f"<b> {token_metadata['data']['name']} (${token_metadata['data']['symbol']}) </b>\n\n"
                    f"📌CA: {base_token['address']}\n"
                    f"🎯Exchange: <b> {token_details['exchange']} </b>\n"
                    f"🪙Market Cap: <b> {format_number(token_details['market_cap'])} </b>\n"
                    f"💧Liquidity: <b> {format_number(token_details['liquidity'])} </b>\n"
                    f"💰Token Price: <b> ${token_details['token_price']} </b>\n\n"
                    f"📖Description: {token_description}\n\n"
                    f"{social_links_str}")
        
        return message, token_image
    else:
        return None, None

def handle_message(update: update, context: CallbackContext):
    if context.user_data.get('adding_token'):
        token_address = update.message.text
        message, token_image = token_details(token_address)

        if message:
            if token_image:
                update.message.reply_photo(
                    photo=token_image,
                    caption=message,
                    parse_mode=ParseMode.HTML
                )
            else:
                update.message.reply_text(message, parse_mode=ParseMode.HTML)
            
            update.message.reply_text('Set an alert: /alert <price_usd/market_cap/liquidity> <value>')
            context.user_data['adding_token'] = False
            context.user_data['token_address'] = token_address
        else:
            update.message.reply_text('Invalid token address or unable to fetch token details. Please try again.')

def start(update: update, context: CallbackContext):
    update.message.reply_text('Welcome to the Solana WatchDog Bot! Use /add_token to track a token.')   
    
def add_token(update: update, context: CallbackContext):
    update.message.reply_text('Please enter the solana token address: ')
    context.user_data['adding_token'] = True
    
def set_alert(update: update, context: CallbackContext):
    user_id = update.message.chat_id
    args = context.args
    
    if len(args) != 2:
        update.message.reply_text('Usage: /alert <price_usd/market_cap/liquidity> <value>')
        return
    
    condition, threshold = args[0], float(args[1])
    token_address = context.user_data.get('token_address')
    
    if token_address:
        alert = {
            'user_id': user_id,
            'token_address': token_address,
            'condition': condition,
            'threshold': threshold
        }
        alerts_collection.insert_one(alert)
        update.message.reply_text('Alert created successfuly! Use /track_alerts to track open alerts.')
    
def check_alerts():
    alerts = alerts_collection.find()
    for alert in alerts:
        token_address = alert['token_address']
        user_id = alert['user_id']
        condition = alert['condition']
        threshold = alert['threshold']
        token_details = get_token_details_dexscreener(token_address)
        
        if condition == 'price_usd' and token_details['token_price'] >= threshold:
            updater.bot.send_message(chat_id=user_id, text=f'Token {token_address} has reached the price of ${threshold} USD.')
        elif condition == 'market_cap' and token_details['market_cap'] >= threshold:
            updater.bot.send_message(chat_id=user_id, text=f'Token {token_address} has reached the market cap of ${threshold}.')
        elif condition == 'liquidity' and token_details['liquidity'] >= threshold:
            updater.bot.send_message(chat_id=user_id, text=f'Token {token_address} has reached the liquidity of ${threshold}.')
 

updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("add_token", add_token))
dispatcher.add_handler(CommandHandler("alert", set_alert))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

scheduler = BackgroundScheduler()
scheduler.add_job(check_alerts, 'interval', minutes=1)
scheduler.start()

updater.start_polling()
updater.idle()

