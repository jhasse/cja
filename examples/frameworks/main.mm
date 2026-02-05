#include <CoreFoundation/CoreFoundation.h>
#include <CoreText/CoreText.h>

int main() {
    CFStringRef name = CFStringCreateWithCString(
        kCFAllocatorDefault, "Helvetica", kCFStringEncodingUTF8);
    CTFontRef font = CTFontCreateWithName(name, 12.0, nullptr);
    if (font) {
        CFRelease(font);
    }
    CFRelease(name);
    return 0;
}
