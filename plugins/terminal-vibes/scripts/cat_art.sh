#!/bin/bash
# Random cat ASCII art with color

pick=$((RANDOM % 5))

case $pick in
0)
cat << 'EOF'

   /\_/\
  ( o.o )
   > ^ <
   meow~

EOF
;;
1)
cat << 'EOF'

   /\___/\
  (  o o  )
  (  =^=  )
   (______)
    |||  |||
   nyaa~

EOF
;;
2)
cat << 'EOF'

      /\_____/\
     /  o   o  \
    ( ==  ^  == )
     )         (
    (           )
   ( (  )   (  ) )
  (__(__)___(__)__)
    purrr~

EOF
;;
3)
cat << 'EOF'

  |\      _,,,---,,_
  /,`.-'`'    -.  ;-;;,_
 |,4-  ) )-,_. ,\ (  `'-'
'---''(_/--'  `-'\_)
  Felix the Cat!

EOF
;;
4)
cat << 'EOF'

   A___A
  | o o |
  |  >  |
  |_____|
  || | ||
  || | ||
  "" | ""
  standing cat!

EOF
;;
esac
