#!/bin/bash
# Dad jokes / puns raining from the sky

declare -a JOKES
JOKES[0]="Why do programmers prefer dark mode? Because light attracts bugs."
JOKES[1]="A SQL query walks into a bar, sees two tables and asks... Can I JOIN you?"
JOKES[2]="Why was the JavaScript developer sad? He didn't Node how to Express himself."
JOKES[3]="What's a programmer's favorite hangout? Foo Bar."
JOKES[4]="Why do Java developers wear glasses? Because they can't C#."
JOKES[5]="How many programmers to change a light bulb? None. That's a hardware problem."
JOKES[6]="!false ... it's funny because it's true."
JOKES[7]="There are 10 types of people: those who understand binary and those who don't."
JOKES[8]="Why did the developer go broke? He used up all his cache."
JOKES[9]="What do you call a snake that is 3.14 meters long? A Pi-thon."
JOKES[10]="ASCII a stupid question, get a stupid ANSI."
JOKES[11]="Knock knock. Race condition. Who's there?"
JOKES[12]="git commit -m 'fixed bugs' ... narrator: he had not fixed the bugs."
JOKES[13]="Why do functions always win arguments? They have valid points to return."
JOKES[14]="What is a ghost's favorite data type? Boo-lean."

COLS=$(tput cols 2>/dev/null || echo 80)
MAX_INDENT=$((COLS / 4))

echo ""
printf "\033[1;33m  === DAD JOKE RAIN ===\033[0m\n"
echo ""

for i in $(seq 0 4); do
  IDX=$((RANDOM % ${#JOKES[@]}))
  JOKE="${JOKES[$IDX]}"

  INDENT=$((RANDOM % MAX_INDENT))
  SPACES=$(printf '%*s' "$INDENT" '')

  COLOR_NUM=$((31 + (RANDOM % 6)))

  printf "%s\033[%dm>> %s\033[0m\n\n" "$SPACES" "$COLOR_NUM" "$JOKE"
  sleep 0.3
done

printf "\033[2m  ...ba dum tss!\033[0m\n\n"
