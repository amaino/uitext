#!/usr/bin/env python3

""" Utility for UI testing - convert an HTML dump to an ASCII screenshot"""

import sys, os
from html.parser import HTMLParser
from gridformatter import GridFormatter, GridFormatterWithHeader
from traceback import format_exception
import argparse

def getExceptionString():
    return "".join(format_exception(*sys.exc_info()))


def get_attr_value(attrs, name):
    for attr, val in attrs:
        if attr == name:
            return val

def getUnderline(text):
    prevNewLinePos = text.rfind("\n")
    lineLen = len(text) - prevNewLinePos - 1
    return "\n" + "=" * lineLen + "\n\n"

def shouldAddWhitespace(text, existingText):
    if len(existingText) == 0:
        return False

    lastChar = existingText[-1]
    if text.startswith("\n"):
        return lastChar != "\n"
    else:
        return not lastChar.isspace()

class ModalAbort(Exception):
    pass

class HtmlExtractParser(HTMLParser):
    voidTags = [ 'area', 'base', 'br', 'col', 'command', 'embed', 'hr', 'img', 'input', 'keygen', 'link', 'meta', 'param', 'source', 'track', 'wbr' ]
    def __init__(self, toIgnore=set(), iconProperties=set(), modalProperties=set(), show_invisible=False):
        HTMLParser.__init__(self)
        self.currentSubParsers = []
        self.inBody = False
        self.inScript = False
        self.inSuperscript = False
        self.linkStart = None
        self.text = ""
        self.liLevel = 0
        self.level = 0
        self.modalDivLevel = None
        self.flexData = {}
        self.beforeDataText = ""
        self.afterDataText = ""
        self.propertiesToIgnore = toIgnore
        self.iconProperties = iconProperties
        self.modalProperties = modalProperties
        self.ignoreUntilCloseTag = ""
        self.ignoreRecursionLevel = 0
        self.show_invisible = show_invisible

    def parse(self, text):
        try:
            self.feed(text)
        except ModalAbort:
            pass
        except:
            sys.stderr.write("Failed to parse browser text:\n")
            sys.stderr.write(getExceptionString())
            sys.stderr.write("Original text follows:\n")
            sys.stderr.write(text + "\n")
        return self.text

    def getElementProperties(self, attrs):
        cls = get_attr_value(attrs, "class")
        elementProperties = set(cls.split()) if cls else set()
        for idAttr in [ "id", "data-test-id" ]:
            id = get_attr_value(attrs, idAttr)
            if id in self.iconProperties:
                elementProperties.add(id)
        return elementProperties

    def get_icon_name(self, elementProperties):
        is_icon = "icon" in elementProperties
        if is_icon:
            elementProperties.remove("icon")

        chosenProperties = self.iconProperties & elementProperties
        if not is_icon or len(chosenProperties) > 0:
            elementProperties = chosenProperties
        if elementProperties:
            shortnames = [ name.split("__")[-1] for name in elementProperties ]
            return ":" + " ".join(sorted(shortnames)) + ":"
        else:
            return ""

    def is_invisible(self, attrs, display):
        return not self.show_invisible and (display == "none" or get_attr_value(attrs, "visibility") == "hidden")

    def is_block_display(self, name, display):
        # ignore when we expect it anyway
        if name in ("div", "h1", "h2", "h3", "h4", "span", "button", "th", "td", "input"):
            return False
        else:
            return display == "block"

    def get_display_style(self, attrs):
        test_display = get_attr_value(attrs, "data-test-explicit-display")
        if test_display:
            return test_display
        style = get_attr_value(attrs, "style")
        if style is not None:
            displayKey = "display: "
            pos = style.find(displayKey)
            if pos != -1:
                remains = style[pos + len(displayKey):]
                return remains.split(";", 1)[0]
        return "unknown"

    def handle_starttag(self, rawname, attrs):
        self.afterDataText = self.afterDataText.rstrip()
        name = rawname.lower()
        if name not in self.voidTags:
            self.level += 1
        elementProperties = self.getElementProperties(attrs)
        display = self.get_display_style(attrs)
        if self.ignoreUntilCloseTag:
            if self.ignoreUntilCloseTag == name:
                self.ignoreRecursionLevel += 1
        elif not self.propertiesToIgnore.isdisjoint(elementProperties) or self.is_invisible(attrs, display) or name == "noscript": # If Javascript is disabled then we won't be able to test it anyway...
            # if the name is a void tag like "input", close tag will never come. Ignore this but don't set anything else.
            if name not in self.voidTags:
                self.ignoreUntilCloseTag = name
                self.ignoreRecursionLevel = 1
        elif name == "table":
            if len(self.currentSubParsers) > 0:
                self.currentSubParsers[-1].addText("\n")  
            elif not self.text.endswith("\n"):
                self.text += "\n"
            self.currentSubParsers.append(TableParser())
        elif name == "select":
            if not self.text.endswith("\n"):
                self.text += "\n"
            self.currentSubParsers.append(SelectParser())
        else:
            if elementProperties and (name == "i" or not self.iconProperties.isdisjoint(elementProperties)):
                self.afterDataText += self.get_icon_name(elementProperties)
            elif name == "img":
                self.handle_data("Image '" + os.path.basename(get_attr_value(attrs, "src")) + "'")
            elif name == "iframe":
                self.handle_data("IFrame '" + get_attr_value(attrs, "src") + "'")

            if self.is_block_display(name, display):
                self.afterDataText += "\n"
            elif display == "flex":
                flexTag = name
                self.flexData[self.level] = flexTag, len(self.text)

            if name == "button":
                self.handle_data("Button '")
            elif name == "nav":
                self.addText("\n(Navigation:\n")
            elif name == "li":
                indent = ""
                if self.liLevel > 1:
                    self.addText("\n")
                    indent = "  " * self.liLevel
                self.addText(indent + "- ")
                self.liLevel += 1
            elif name == "br":
                self.addText("\n")
            elif name == "input":
                input_type = get_attr_value(attrs, "type")
                if input_type in ("text", "datetime-local", "password"):
                    text = "=== "
                    placeholder = get_attr_value(attrs, "placeholder")
                    if placeholder:
                        text += "_" + placeholder + "_"
                    text += " ==="
                    if input_type in ("password", "datetime-local"):
                        text += " (" + input_type + ")"
                    self.handle_data(text)
                elif input_type == "button":
                    value = get_attr_value(attrs, "value")
                    self.handle_data("Button '" + value + "'")
                elif input_type == "radio":
                    self.handle_data("( ) ")
                elif input_type == "checkbox":
                    self.handle_data("[ ] ")

            elif name == "textarea":
                self.addText("\n" + "=" * 10 + "\n")
            elif name == "b":
                self.addText("*")
            elif name == "sup":
                self.inSuperscript = True
                self.addText("^")
            elif self.currentSubParsers:
                self.currentSubParsers[-1].startElement(name, attrs)
            elif name == "body":
                self.inBody = True
            elif name == "script":
                self.inScript = True
            elif name == "hr":
                if not self.text.endswith("\n"):
                    self.text += "\n"
                self.text += "_" * 100 + "\n"
            elif name == "a":
                self.linkStart = len(self.text)
            elif name == "footer":
                self.addText("\n")
            elif name == "div":
                if not self.in_flex() and not self.text.endswith("\n"):
                    self.beforeDataText = "\n"
                if elementProperties and any((className in elementProperties for className in self.modalProperties)):
                    self.modalDivLevel = self.level
                    self.reset_for_dialog()
                    self.addText("\n" + " Modal dialog ".center(50, "_") + "\n")
            elif self.text.strip() and name in [ "h1", "h2", "h3", "h4" ]:
                while not self.text.endswith("\n\n"):
                    self.text += "\n"
                    
    def reset_for_dialog(self):
        self.text = ""
        self.flexData.clear()
        self.beforeDataText = ""
        self.afterDataText = ""
        
    def in_flex(self):
        if self.level - 1 not in self.flexData:
            return False

        _, flexStartPos = self.flexData.get(self.level - 1)
        textSinceFlexStart = self.text[flexStartPos:]
        return "\n" not in textSinceFlexStart.strip()

    def handle_endtag(self, rawname):
        name = rawname.lower()
        self.beforeDataText = ""
        self.handle_after_data_text()
        for flexDivLevel, (flexTag, _) in self.flexData.items():
            if name == flexTag and self.level == flexDivLevel:
                del self.flexData[flexDivLevel]
                if not self.in_flex():
                    self.addText("\n")
                break
        if self.ignoreUntilCloseTag:
            if self.ignoreUntilCloseTag == name:
                self.ignoreRecursionLevel -= 1
                if self.ignoreRecursionLevel == 0:
                    self.ignoreUntilCloseTag = ""
        elif name in [ "select", "table" ]:
            parser = self.currentSubParsers.pop()
            currText = parser.getText()
            if self.currentSubParsers:
                self.currentSubParsers[-1].addText(currText)
            else:
                self.text += currText
                if not currText.endswith("\n"):
                    self.text += "\n"
        elif name == "button":
            self.handle_data("'")
        elif name == "sup":
            self.inSuperscript = False
        elif name == "b":
            self.addText("*")
        elif name == "li":
            self.liLevel -= 1
            self.addText("\n")
        elif self.currentSubParsers and name != "img":
            self.currentSubParsers[-1].endElement(name)
        elif name == "div":
            if self.level == self.modalDivLevel:
                self.modalDivLevel = None
                self.handle_data("_" * 50)
                raise ModalAbort()
            if self.in_flex():
                self.text = self.text.rstrip("\n")
            else:
                if not self.text.endswith("\n"):
                    self.addText("\n")
        elif name == "nav":
            self.addText(")")
        elif name == "textarea":
            self.addText("\n" + "=" * 10)
        elif name == "script":
            self.inScript = False
        elif name in [ "h1", "h2", "h3", "h4" ]:
            self.text += getUnderline(self.text)
        elif name == "a":
            linkText = self.text[self.linkStart:].strip()
            if "\n" in linkText:
                # make sure multiline links hang together
                self.text = self.text[:self.linkStart] + "\n"
                lines = linkText.splitlines()
                width = max((len(line) for line in lines))
                for line in lines:
                    self.text += line.ljust(width) + "->\n"
            else:
                self.text = self.text[:self.linkStart] + linkText + "->  "
            self.linkStart = None
        self.level -= 1

    def fixWhitespace(self, line):
        if self.inSuperscript:
            return line.strip()
        while "  " in line:
            line = line.replace("  ", " ")
        return line

    def handle_after_data_text(self):
        if self.afterDataText:
            if self.afterDataText.endswith("\n\n"):
                self.afterDataText = self.afterDataText.rstrip() + "\n"
            self.addText(self.afterDataText)
            self.afterDataText = ""

    def handle_data(self, content):
        if not self.ignoreUntilCloseTag:
            if content == '\xa0': # non-breaking space, remove block lines
                self.addText(" ")
                self.afterDataText = self.afterDataText.rstrip()
                self.handle_after_data_text()

            if not content.strip():
                return
            newLines = [ line.rstrip("\t\r\n") for line in content.splitlines() ]
            text = self.fixWhitespace(" ".join(newLines))
            if self.beforeDataText:
                self.addText(self.beforeDataText)
                self.beforeDataText = ""
            self.addText(text)
            if text:
                self.handle_after_data_text()

    def quotes_matched_in_line(self):
        pos = self.text.rfind("\n")
        return self.text[pos:].count("'") % 2 == 0

    def needs_space(self, text, origText):
        if len(origText) == 0 or len(text) == 0:
            return False

        newChar = text[0]
        lastChar = origText[-1]
        newCharContent = newChar.isalnum() or newChar in '(='
        lastCharContent = lastChar.isalnum() or lastChar in '):'
        if newCharContent == lastCharContent:
            return newCharContent

        if newChar != "'" and lastChar != "'":
            return False

        return self.quotes_matched_in_line()

    def addText(self, text):
        if self.currentSubParsers:
            self.currentSubParsers[-1].addText(text)
        elif self.inBody and not self.inScript:
            if not text.isspace() or shouldAddWhitespace(text, self.text):
                if self.needs_space(text, self.text):
                    self.text += " "
                self.text += text

class SelectParser:
    def __init__(self):
        self.options = []
        self.inOption = False

    def startElement(self, name, attrs):
        if name == "option":
            self.options.append("")
            self.inOption = True

    def endElement(self, name):
        if name == "option":
            self.inOption = False

    def addText(self, text):
        if self.inOption:
            self.options[-1] += text

    def getText(self):
        return "Dropdown (" + ", ".join(self.options) + ")"


class TableParser:
    def __init__(self):
        self.headerRows = []
        self.currentRow = None
        self.currentRowIsHeader = True
        self.grid = []
        self.activeElements = {}

    def isCell(self, name):
        return name in ["td", "th"]

    def isRow(self, name):
        return name in ["tr", "thead"]

    def startElement(self, name, attrs):
        self.activeElements[name] = attrs
        if self.isRow(name):
            self.currentRow = []
        elif self.isCell(name):
            if self.currentRow is None:
                sys.stderr.write("ERROR: Received '" + name + "' element in unexpected context (no table row). Attrs = " + repr(attrs) + "\n")
                sys.stderr.write("Grid so far = " + repr(self.grid) + "\n")
            else:
                self.currentRow.append("")
                if name == "td" and "thead" not in self.activeElements:
                    self.currentRowIsHeader = False
        elif name == "div" and self.currentRow is not None and len(self.currentRow) and \
            self.currentRow[-1].strip() and not self.currentRow[-1].endswith("\n"):
            self.currentRow[-1] += "\n"

    def endElement(self, name):
        if name in self.activeElements:  # Don't fail on duplicated end tags
            if self.currentRow is not None and self.isCell(name):
                if self.currentRow[-1].endswith("\n"):
                    self.currentRow[-1] = self.currentRow[-1].rstrip()
                colspan = get_attr_value(self.activeElements[name], "colspan")
                if colspan:
                    for _ in range(int(colspan) - 1):
                        self.currentRow.append("")
            del self.activeElements[name]
            if self.isRow(name) and self.currentRow is not None:
                if len(self.currentRow):
                    if self.currentRowIsHeader:
                        self.headerRows.append(self.currentRow)
                    else:
                        self.grid.append(self.currentRow)
                self.currentRow = None
            if name in [ "h1", "h2", "h3", "h4"] and self.currentRow:
                self.addText(getUnderline(self.currentRow[-1]))

    def getText(self):
        if len(self.grid) == 0:
            return ""

        columnCount = max((len(r) for r in self.grid))
        if self.headerRows:
            columnCountHeader = max((len(r) for r in self.headerRows))
            columnCount = max(columnCountHeader, columnCount)
            formatter = GridFormatterWithHeader(self.headerRows, self.grid, columnCount, allowHeaderOverlap=True)
        else:
            formatter = GridFormatter(self.grid, columnCount)
        return str(formatter)

    def isSpaces(self, text):
        return len(text) and all((c == " " for c in text))

    def addText(self, text):
        if self.currentRow is not None:
            if len(self.currentRow):
                if text.strip() or shouldAddWhitespace(text, self.currentRow[-1]):
                    self.currentRow[-1] += text
            elif text.strip():
                self.currentRowIsHeader = False
                self.currentRow.append(text)

def parseList(text):
    return set(text.split(",")) if text else set()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Program to write HTML as ASCII art, suitable for e.g. TextTest testing')
    parser.add_argument('--ignore', default="", help='Comma-separated list of CSS classes to ignore')
    parser.add_argument('--icons', default="", help='Comma-separated list of CSS classes to treat as icons')
    parser.add_argument('--modals', default="", help='Comma-separated list of CSS classes to treat as modal dialogs')
    parser.add_argument('--show-invisible', action='store_true', help='Show all elements, even if invisible. Mainly useful for simplifying tests by avoiding extra clicks')
    parser.add_argument('filenames', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    toIgnore = parseList(args.ignore)
    iconProperties = parseList(args.icons)
    modalProperties = parseList(args.modals)
    multiple = len(args.filenames) > 1
    for i, filename in enumerate(args.filenames):
        if multiple and i > 0:
            print()
        if multiple:
            stage = os.path.basename(filename).split(".", 1)[0]
            if len(stage) > 3 and stage[3] == "_" and stage[:3].isdigit():
                stage = stage[4:]
            stage = " " + stage + " "
            print(stage.center(30, "-"))
        text = open(filename).read()
        parser = HtmlExtractParser(toIgnore, iconProperties, modalProperties, args.show_invisible)
        print(parser.parse(text))
