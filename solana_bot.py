from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext, Filters
from telegram import update
from telegram import chat
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.rpc.requests import GetTokenLargestAccounts
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import asyncio
from dotenv import load_dotenv
import os
import logging

load_dotenv

# Implement logger
logging.basicConfig(
    filename='extract.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s'
)

# Replace with your actual token and MongoDB connection string
TELEGRAM_BOT_TOKEN = "7276720313:AAFdKC4B9U8VNou8IbdHvfPDi3srng5CGno"
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

def get_token_details_dexscreener(token_address: str):

    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    
    try:
        response = requests.get(url)
    
        if response.status_code == 200:
            data = response.json()
            
            logging.info('Token Details Successfully retrieved from DexScreener')
            
            if 'pairs' in data:
                pair_data = data['pairs'][0]
                return {
                    'exchange': pair_data['dexId'],
                    'market_cap': pair_data['fdv'],
                    'liquidity': pair_data['liquidity']['usd'],
                    'token_price': pair_data['priceUsd']
                }
    except:
        logging.warning('Dexscreener data not successfully retrieved')
        return None

def get_token_holders(client, token_address):
    pubkey = Pubkey.from_string(token_address)
    request = GetTokenLargestAccounts(pubkey)
    try:
        response = client.send(request)
        if response.is_ok():
            largest_accounts = response.unwrap().value
            holders = [(account.address.to_string(), account.amount) for account in largest_accounts]
            logging.info('Token Holders Successfully retrieved')
            return holders
        else:
            return None
    except Exception as e:
        logging.warning(f"Token Holders not retrieved. Error Message: {e}")


def handle_message(update: update, context: CallbackContext):
    if context.user_data.get('adding_token'):
        token_address = update.message.text
        #async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
            # token_metadata = await get_token_metadata(client, token_address)
            #token_holders = await get_token_holders(token_address)
            
        token_details = get_token_details_dexscreener(token_address)
        #token_holders = get_token_holders(token_address)

        if token_details:
            #holders_info = "\n".join([f"Address: {holder[0]}, Amount: {holder[1]}" for holder in token_holders])
            message = (f"Token details:\n"
                       #f"Name: {token_metadata['name']}\n"
                       #f"Symbol: {token_metadata['symbol']}\n"
                       f"Exchange: {token_details['exchange']}\n"
                       f"Market Cap: ${token_details['market_cap']}\n"
                       f"Liquidity: ${token_details['liquidity']}\n"
                       f"Price: ${token_details['token_price']}\n")
                       #f"Token Holders:\n{holders_info}")
            update.message.reply_text(message)
            update.message.reply_text('Set an alert: /alert <price_usd/market_cap/liquidity> <value>')
            context.user_data['adding_token'] = False
            context.user_data['token_address'] = token_address
        else:
            update.message.reply_text('Invalid token address or unable to fetch token details. Please try again.')

def start(update: update, context: CallbackContext):
    update.message.reply_text('Welcome to the Solana WatchDog Bot! Use /addtoken to track a token.')   
    
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
        update.message.reply_text('Alert created successfuly! Use /trackalerts to track open alerts.')
    
def check_alerts():
    alerts = alerts_collection.find()
    for alert in alerts:
        token_address = alert['token_address']
        user_id = alert['user_id']
        condition = alert['condition']
        threshold = alert['threshold']
        token_details = get_token_details_dexscreener(token_address)
        
        if condition == 'price_usd' and token_details['price'] >= threshold:
            updater.bot.send_message(chat_id=user_id, text=f'Token {token_address} has reached the price of ${threshold} USD.')
        elif condition == 'market_cap' and token_details['market_cap'] >= threshold:
            updater.bot.send_message(chat_id=user_id, text=f'Token {token_address} has reached the market cap of ${threshold}.')
        elif condition == 'liquidity' and token_details['liquidity'] >= threshold:
            updater.bot.send_message(chat_id=user_id, text=f'Token {token_address} has reached the liquidity of ${threshold}.')
 

updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("addtoken", add_token))
dispatcher.add_handler(CommandHandler("alert", set_alert))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

scheduler = BackgroundScheduler()
scheduler.add_job(check_alerts, 'interval', minutes=1)
scheduler.start()

updater.start_polling()
updater.idle()

