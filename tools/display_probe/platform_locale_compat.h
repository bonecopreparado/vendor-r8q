// SPDX-License-Identifier: Apache-2.0
// Compile-only compatibility between the pinned VNDK30 libc++ headers and the
// pinned NDK27 Bionic API30 sysroot. No platform/vendor header is modified.
#pragma once

#include <android/ndk-version.h>
#include <ctype.h>
#include <locale.h>
#include <string.h>
#include <time.h>
#include <wchar.h>
#include <wctype.h>

#if !defined(__BIONIC__) || !defined(__ANDROID_API__) || __ANDROID_API__ != 30
#error "This locale compatibility is reviewed only for Bionic Android API30"
#endif
#if __NDK_MAJOR__ != 27 || __NDK_MINOR__ != 2
#error "This locale compatibility is reviewed only with pinned NDK r27c"
#endif

// All POSIX locale variants in the obsolete libc++ fallback are already
// declared by this Bionic sysroot. Taking their addresses verifies that claim
// at compile time; there is no replacement implementation or changed C++ ABI.
namespace r8q_locale_compile_check {
#define R8Q_REQUIRE_LOCALE(name) [[maybe_unused]] constexpr auto have_##name = &::name
R8Q_REQUIRE_LOCALE(isalnum_l);
R8Q_REQUIRE_LOCALE(isalpha_l);
R8Q_REQUIRE_LOCALE(isblank_l);
R8Q_REQUIRE_LOCALE(iscntrl_l);
R8Q_REQUIRE_LOCALE(isdigit_l);
R8Q_REQUIRE_LOCALE(isgraph_l);
R8Q_REQUIRE_LOCALE(islower_l);
R8Q_REQUIRE_LOCALE(isprint_l);
R8Q_REQUIRE_LOCALE(ispunct_l);
R8Q_REQUIRE_LOCALE(isspace_l);
R8Q_REQUIRE_LOCALE(isupper_l);
R8Q_REQUIRE_LOCALE(isxdigit_l);
R8Q_REQUIRE_LOCALE(iswalnum_l);
R8Q_REQUIRE_LOCALE(iswalpha_l);
R8Q_REQUIRE_LOCALE(iswblank_l);
R8Q_REQUIRE_LOCALE(iswcntrl_l);
R8Q_REQUIRE_LOCALE(iswdigit_l);
R8Q_REQUIRE_LOCALE(iswgraph_l);
R8Q_REQUIRE_LOCALE(iswlower_l);
R8Q_REQUIRE_LOCALE(iswprint_l);
R8Q_REQUIRE_LOCALE(iswpunct_l);
R8Q_REQUIRE_LOCALE(iswspace_l);
R8Q_REQUIRE_LOCALE(iswupper_l);
R8Q_REQUIRE_LOCALE(iswxdigit_l);
R8Q_REQUIRE_LOCALE(toupper_l);
R8Q_REQUIRE_LOCALE(tolower_l);
R8Q_REQUIRE_LOCALE(towupper_l);
R8Q_REQUIRE_LOCALE(towlower_l);
R8Q_REQUIRE_LOCALE(strcoll_l);
R8Q_REQUIRE_LOCALE(strxfrm_l);
R8Q_REQUIRE_LOCALE(strftime_l);
R8Q_REQUIRE_LOCALE(wcscoll_l);
R8Q_REQUIRE_LOCALE(wcsxfrm_l);
#undef R8Q_REQUIRE_LOCALE
}  // namespace r8q_locale_compile_check

// VNDK30 libc++ includes this old fallback unconditionally on Android, causing
// redefinition of NDK27's inline ctype functions. Use Bionic's existing POSIX
// locale API instead. In particular, do not redefine __ANDROID__ or __BIONIC__.
#define _LIBCPP_SUPPORT_XLOCALE_POSIX_L_FALLBACK_H
