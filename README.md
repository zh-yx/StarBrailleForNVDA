# StarBrailleDisplay driver for NVDA

An NVDA driver add-on for the integrated braille display of the Word-Star Braille Laptop, used by the China Braille Press.

## Features

- Displays NVDA output on the braille display.
- Detects routing cursor keys and other hardware buttons and reports them to NVDA.

## Installation

Download the latest add-on package from the GitHub Releases page and install it in NVDA.

## Button Layout

The Word-Star Braille Laptop is currently supported. Its button layout is described below.

### Word-Star Braille Laptop Button Layout

- Each braille cell has a corresponding routing cursor key above it. Pressing a routing key moves the edit cursor to the corresponding position.
- There are six buttons at the bottom of the device. The left and right sides each have a pair of two buttons, and there are two standalone buttons in the middle.
- From left to right, the buttons are:
  1. `previousLine` — default: previous line
  2. `previousScreen` — default: previous screen
  3. `buttonLeft` — default: Tab
  4. `buttonRight` — default: Enter
  5. `nextScreen` — default: next screen
  6. `nextLine` — default: next line

The `buttonLeft` and `buttonRight` gestures are intended as user-customizable keys. Their default actions can be changed in NVDA's Input Gestures dialog.
