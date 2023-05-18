import asyncio
import datetime
import logging
from typing import Union

import discord
import pytz
import yaml
from discord import channel, option
from discord.ext import commands
from discord.utils import get
import pprint

# TODO: Link to function that creates an event in the server
# TODO: Create dynamic embed that has dropdown to select job
# and updates with attendees and their respective jobs
# TODO: Create temp VC for event? If so, end event when last person leaves VC.

# Read config file
with open("config.yml", "r") as ymlfile:
    config = yaml.load(ymlfile, Loader=yaml.Loader)

# Setup logging
logging.basicConfig(level=logging.INFO)

bot = discord.Bot(debug_guilds=[config["guildid"]])


# TODO: This is an example stub of how to create a view for later.
class DropdownView(discord.ui.View):
    @discord.ui.channel_select(
        placeholder="Select channels...", min_values=1, max_values=3
    )  # Users can select a maximum of 3 channels in the dropdown
    async def channel_select_dropdown(
        self, select: discord.ui.Select, interaction: discord.Interaction
    ) -> None:
        await interaction.response.send_message(
            f"You selected the following channels:"
            + f", ".join(f"{channel.mention}" for channel in select.values)
        )


# Create an event embed
def create_embed(event_name, description, field_value, footer):
    embed = discord.Embed(
        title=f'__{event_name}__',
        description=description,
        color=discord.Colour.blurple(),
    )

    embed.add_field(
        name="__Note__",
        value="Use the /event_signup command to register for the event.",
        inline=False,
    )
    embed.add_field(name="__Attending__", value=field_value, inline=False)
    embed.add_field(name="__Tentative__", value=field_value, inline=False)

    embed.set_footer(text=footer)

    return embed


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("--------------------------")


# Ping
@bot.slash_command()
async def ping(ctx):
    await ctx.respond(f"Pong! {round(bot.latency)}ms")


# New event slash command
hours_list = list(range(1, 13))
minutes_list = ["00", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55"]
duration_list = [1, 2, 3, 4, 5, 6]


# Create slash command
@bot.slash_command(name="new_event")
@option("event_name", description="Event name")
@option("description", description="Event description")
@option("date", description="Date of the event in MM-dd format (Example: 5-23)")
@option("hour", description="hour", choices=hours_list)
@option("minute", description="minute", choices=minutes_list)
@option("am_pm", description="AM/PM", choices=["AM", "PM"])
@option("duration", description="Duration of the event in HOURS", choices=duration_list)
@option("location", description="Voice channel for the event")
@option("ping_role", description="Choose a role to ping")
async def new_event(
    ctx: discord.ApplicationContext,
    event_name: str,
    description: str,
    date: str,
    hour: int,
    minute: str,
    am_pm: str,
    duration: int,
    location: discord.VoiceChannel,
    ping_role: discord.Role
):
    """Create a new event."""

    # If PM, add 12 to conver to 24hr
    if am_pm == "PM":
        hour += 12

    # Convert time to datetime object
    # TODO: Warn when trying to schedule event in the past.
    # Disc associated warning: "In scheduled_start_time: Cannot schedule event in the past."

    # Setup user's time zone
    if str(ctx.author) in config["time_zone"]["US/Pacific"]:
        user_tz = pytz.timezone("US/Pacific")
    elif str(ctx.author) in config["time_zone"]["US/Central"]:
        user_tz = pytz.timezone("US/Central")
    elif str(ctx.author) in config["time_zone"]["US/Eastern"]:
        user_tz = pytz.timezone("US/Eastern")
    elif str(ctx.author) in config["time_zone"]["Europe/Oslo"]:
        user_tz = pytz.timezone("Europe/Oslo")

    user_tz_naive = datetime.datetime.strptime(
        f"2023-{date} {hour}:{minute}", "%Y-%m-%d %H:%M"
    )
    user_tz_dt = user_tz.localize(user_tz_naive, is_dst=True)
    utc_dt = user_tz_dt.astimezone(pytz.utc)
    discord_tz_dt = discord.utils.format_dt(user_tz_dt)

    # Set static forum channel. Make dynamic later.
    forum_channel = bot.get_channel(config["channelid"])

    # Create initial message
    embed = create_embed(event_name, description, "", "")

    # Create and send forum thread
    thread = await forum_channel.create_thread(
        name=event_name,
        embed=embed,
        content=f"{discord_tz_dt}\nDuration: {duration} hr(s)\n{ping_role.mention}",
    )

    print(f"starting_message.id: {thread.starting_message.id}")
    # Update embed with message.id
    new_embed = create_embed(
        event_name, description, "", f"ID: {thread.starting_message.id}"
    )

    await thread.starting_message.edit(embed=new_embed)

    # Create server scheduled event
    await ctx.guild.create_scheduled_event(
        name=event_name,
        description=description,
        start_time=utc_dt,
        end_time=utc_dt + datetime.timedelta(0, 0, 0, 0, 0, duration),
        location=location.id,
    )

    await ctx.respond(
        f"Event created! You can find the details below:\n"
        f"Event Name: {event_name}\n"
        f"Description: {description}\n"
        f"Date: {date}\n"
        f"Time: {hour}:{minute}\n"
        f"Duration: {duration} hr(s)\n"
        f"Voice Channel: {location.mention}\n"
        f"Pinged Role: {ping_role.mention}",
        ephemeral=True,
        delete_after=30,
    )


# Alternative way for users to register if embedded dropdown is being weird
# TODO: Add job emoji server values
job_list = [
    "PLD",
    "WAR",
    "DRK",
    "GNB",
    "WHM",
    "SCH",
    "AST",
    "SGE",
    "MNK",
    "DRG",
    "NIN",
    "SAM",
    "RPR",
    "BRD",
    "MCH",
    "DNC",
    "BLM",
    "SMN",
    "RDM",
]


@bot.slash_command()
@option("job", description="Select the job you will attend as", choices=job_list)
@option(
    "status",
    description="Attending status.",
    choices=["Attending", "Tentative", "Unregister"],
)
async def event_signup(
    ctx: discord.ApplicationContext,
    job: str,
    status: str,
):
    user_nick = str(ctx.user.nick)
    thread = ctx.channel
    attendees_list = ""
    prev_status = ""

    # Fetch first message of thread to get embed
    async for message in thread.history(limit=1, oldest_first=True):
        first_message = message
    # If the first message's author isn't a bot, exit since not an event thread
    if first_message.author.bot is False:
        await ctx.respond(
            "You can only use this command in an event thread",
            ephemeral=True,
            delete_after=30,
        )
        return

    # Convert embed to a dict
    embed_dict = first_message.embeds[0].to_dict()

    # Check if user has already registered (either Attending or Tentative)
    if user_nick in embed_dict["fields"][2]["value"]:
        registered_list = embed_dict["fields"][2]["value"]
        prev_status = "Tentative"
        print(f"registered_list: {registered_list}")
    else:
        registered_list = embed_dict["fields"][1]["value"]
        prev_status = "Attending"

    # If user wants to change their status, remove from list then continue
    if user_nick in registered_list:
        attending_list = registered_list.split("\n")

        # Loop through list and remove user_nick
        temp = 0
        for x in attending_list:
            print(x)
            if user_nick in x:
                attending_list.pop(temp)
            temp += 1

        # Update embed dict with new info
        if prev_status == "Attending":
            embed_dict["fields"][1]["value"] = "".join(attending_list)
        elif prev_status == "Tentative":
            embed_dict["fields"][2]["value"] = "".join(attending_list)
        else:
            print(f"Error while removing user from list to change status.")

        # Convert embed dict back to embed
        new_embed = discord.Embed().from_dict(embed_dict)

        # Update embed info
        await first_message.edit(embed=new_embed)

    # Add user to embed dict's Attendees
    if status == "Attending":
        attendees_list = embed_dict["fields"][1]["value"]

        # Add newline if another user has already registered
        if attendees_list == "":
            attendees_list += f"{job} - {user_nick}"
        else:
            attendees_list += f"\n{job} - {user_nick}"

        # Update embed dict with new Attendees info
        embed_dict["fields"][1]["value"] = attendees_list

        # Convert embed dict back to embed
        new_embed = discord.Embed().from_dict(embed_dict)

        # Update embed info
        await first_message.edit(embed=new_embed)

        # Send confirmation message
        await ctx.respond(
            "You were successfully registered as Attending for the event.",
            ephemeral=True,
            delete_after=30,
        )
    elif status == "Tentative":
        tentative_list = embed_dict["fields"][2]["value"]

        # Add newline if another user has already registered
        if tentative_list == "":
            tentative_list += f"{job} - {user_nick}"
        else:
            tentative_list += f"\n{job} - {user_nick}"

        # Update embed dict with new Tentative info
        embed_dict["fields"][2]["value"] = tentative_list

        # Convert embed dict back to embed
        new_embed = discord.Embed().from_dict(embed_dict)

        # Update embed info
        await first_message.edit(embed=new_embed)

        # Send confirmation message
        await ctx.respond(
            "You were successfully registered as Tentative for the event.",
            ephemeral=True,
            delete_after=30,
        )
    # Remove user from the dict
    elif status == "Unregister":
        prev_status = ""

        if user_nick in embed_dict["fields"][1]["value"]:
            registered_list = embed_dict["fields"][1]["value"].split("\n")
            prev_status = "Attending"
        else:
            registered_list = embed_dict["fields"][2]["value"].split("\n")
            prev_status = "Tentative"

        # Loop through list and remove user_nick
        temp = 0
        for x in registered_list:
            print(x)
            if user_nick in x:
                registered_list.pop(temp)
            temp += 1

        # Update embed dict with new info
        if prev_status == "Attending":
            embed_dict["fields"][1]["value"] = "\n".join(registered_list)
        else:
            embed_dict["fields"][2]["value"] = "\n".join(registered_list)

        # Convert embed dict back to embed
        new_embed = discord.Embed().from_dict(embed_dict)

        # Update embed info
        await first_message.edit(embed=new_embed)

        # Send confirmation message
        await ctx.respond(
            "You were successfully unregistered from the event.",
            ephemeral=True,
            delete_after=30,
        )

    else:
        print(
            "Error. Status not Attending, Tentative, or Unregister. Exiting funciton."
        )
        return

    # TODO: Return error if slash command is used outside of a bot event thread

@bot.slash_command(name="edit_event")
@option("date", description="Date of the event in MM-dd format (Example: 5-23)")
@option("hour", description="hour", choices=hours_list)
@option("minute", description="minute", choices=minutes_list)
@option("am_pm", description="AM/PM", choices=["AM", "PM"])
@option("duration", description="Duration of the event in HOURS", choices=duration_list)
@option("location", description="Voice channel for the event")
@option("ping_role", description="Choose a role to ping")
async def new_event(
    ctx: discord.ApplicationContext,
    date: str,
    hour: int,
    minute: str,
    am_pm: str,
    duration: int,
    location: discord.VoiceChannel,
    ping_role: discord.Role,
):
    """Edit event"""

    # Fetch first message of thread to get message id
    async for message in ctx.channel.history(limit=1, oldest_first=True):
        first_message = message

    # If the first message's author isn't a bot, exit since not an event thread
    if first_message.author.bot is False:
        await ctx.respond(
            "You can only use this command in an event thread",
            ephemeral=True,
            delete_after=30,
        )
        return

    # If PM, add 12 to conver to 24hr
    if am_pm == "PM":
        hour += 12
    
    # Convert time to datetime object
    # TODO: Warn when trying to schedule event in the past.
    # Disc associated warning: "In scheduled_start_time: Cannot schedule event in the past."

    # Setup user's time zone
    if str(ctx.author) in config["time_zone"]["US/Pacific"]:
        user_tz = pytz.timezone("US/Pacific")
    elif str(ctx.author) in config["time_zone"]["US/Central"]:
        user_tz = pytz.timezone("US/Central")
    elif str(ctx.author) in config["time_zone"]["US/Eastern"]:
        user_tz = pytz.timezone("US/Eastern")
    elif str(ctx.author) in config["time_zone"]["Europe/Oslo"]:
        user_tz = pytz.timezone("Europe/Oslo")

    user_tz_naive = datetime.datetime.strptime(
        f"2023-{date} {hour}:{minute}", "%Y-%m-%d %H:%M"
    )
    user_tz_dt = user_tz.localize(user_tz_naive, is_dst=True)
    utc_dt = user_tz_dt.astimezone(pytz.utc)
    discord_tz_dt = discord.utils.format_dt(user_tz_dt)

    # Save embed
    embed = first_message.embeds[0]

    # Edit message
    await first_message.edit(
        content=f"{discord_tz_dt}\nDuration: {duration} hr(s)\n{ping_role.mention}",
        embed=embed
    )

    # Fetch all scheduled events
    s_events = await ctx.guild.fetch_scheduled_events()

    # Get scheduled event ID
    for x in s_events:
        if str(x) == first_message.channel.name:
            scheduled_event = x

    try:
        # Edit scheduled event
        await scheduled_event.edit(
            #name=first_message.channel.name,
            #description=description,
            start_time=utc_dt,
            end_time=utc_dt + datetime.timedelta(0, 0, 0, 0, 0, duration),
            location=location.id,
        )
        # Send confirmation message
        await ctx.respond(
            f"Event edited! Details:\n"
            f"Date: {date}\n"
            f"Time: {hour}:{minute}\n"
            f"Duration: {duration} hr(s)\n"
            f"Voice Channel: {location.mention}\n"
            f"Pinged Role: {ping_role.mention}",
            ephemeral=True,
            delete_after=30,
        )
    except Exception as e:
        print(f'Exception while assigning scheduled_event: {e}')
        await ctx.respond(f"Error, please report to an Admin: {e}")



bot.run(config["token"])
