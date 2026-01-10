# About ninja2bazel

As the name somewhat implies this tool is meant to translate ninja build files to bazel, given that
cmake can generate ninja files it's a great way to bazelify cmake builds.

It has been used successfully to translate complicated builds with more than 3000 files (headers and
sources files) with hundreds of dependencies and tens of folders.

# Using ninja2bazel

It's usually an iterative process, unless you have a dead simple build without any external
dependencies (even openssl) you will most probably to run it multiple time in its simpliest version
you need to provide two arguments: the build.ninja file and the directory with the source of the
code.

## A simple example: hiredis
For instance for the `hiredis` project that is fairly straightforward the command was:
```
parser.py -p "." ~/Work/hiredisbuild/build/build.ninja ~/Work/hiredisbuild/hiredis
```

`-p` specify the prefix in this case `.` means the top level directory in `~/Work/hiredisbuild/hiredis`
It assumed that the code was checked out in ~/Work/hiredisbuild/hiredis and the build file for cmake were in `~/Work/hiredisbuild/build`.

## A more advanced example: foundation DB


First make your task easier: specify only the targets that you need with --top-level-target, in this example we will only bazelify the shared client library: `lib/libfdb_c.dylib` (on a MacOS device, would be lib/libfdb_c.so on a Linux/*BSD).

In this example the code for Foundation DB is checked-out in `~/Work/foundationdb/src` and the build folder for cmake is in `~/Work/foundationdb/build_output/`.

The initial command line is similar to the one of example above with the notable exception of `--top-level-target`.

```
parser.py -p "." --top-level-target lib/libfdb_c.dylib  ~/Work/foundationdb/build_output/build.ninja ~/Work/foundationdb/src/
```

This won't be enough because of third-party dependencies but we will cover that soon after.

Foundation DB bazelification allows us to demonstrate a new capability with `ninja2bazel`, use
pre-built artifacts. It is notouriously public that foundationDB uses mono/c# to generate C++ from
`flow` files but we don't want to deal with that so instead we will use pre-generated files to not
have to deal with mono during the bazel build, of course it means that every time you want to
upgrade your version of foundationDB you have to generate the c++ files from the flow files but
you most probably will have to do the same for the Bazel files so :shrug:.

### Dealing with third-party dependencies
When we inspect the output of `ninja2bazel` we can notice that it prints messages about found
external dependencies, for instance:

```
root - INFO - Marking /opt/homebrew/lib/libcrypto.a as external - Line: 236
root - INFO - Marking /opt/homebrew/Cellar/boost@1.85/1.85.0_3/lib/libboost_context-mt.a as external - Line: 236
```

It has clearly found external dependencies but don't know how to map them to proper bazel
modules, we will have to do that.

Just checking for `Marking .... as external` is not enough usually we have to look for other
signals in the log, don't worry if you don't find them the build will fail at some point and you
will be aware of the missing libs.

### Generating the import file
At this point you need to provide an import file, you can create it manually or it is 2025  you can most probably use codex to cycle through the output of `ninja2bazel` and
generate an import file with the needed external libraries.

But for the sake of this documentation let's assume that we have the following content for the
import file:

```
cc_import(
        name = "libssl",
        static_libs = "/usr/local/lib64/libssl.a",
        hdrs = glob(["/usr/local/include/openssl/*.h"]),
        system_provided = 1,
        alias = "@openssl//:ssl",
)

cc_import(
        name = "boost_context",
        static_libs = "/opt/boost_1_78_0/lib/libboost_context.a",
        hdrs = glob(["/opt/boost_1_78_0/include/boost/context/**.hpp"]),
        system_provided = 1,
        alias = "@boost.context//:boost.context",
)
```

The format for the import file ressemble the one of a Bazel file with `cc_import`,
`ninja2bazel` will use mostly the fields `name`, `alias` (if present) and `hdrs` the rest is not
used for the moment as `ninja2bazel` exclusively relies on headers for the moment to know which
library is needed (this might change in the future).

If you don't specify an alias `ninja2bazel` expect the library to be available in the `cpp_ext_libs`
module, it is available for codebases that use 3rd party libraries that you can't bazelify and
instead want to use a prebuilt version, it is up to you to figure out how to make it available to
`bazel`.
Nowdays I tend to prefer to use a library with an `alias` defined and point to a bcr module as it is
the case for the two libraries above.

### Using the import file

Armed with the new import file it's now time to tell `ninja2bazel` to use it, let's add `--imports my_import_file`:
```
parser.py -p "." --top-level-target lib/libfdb_c.dylib --imports my_import_file ~/Work/foundationdb/build_output/build.ninja ~/Work/foundationdb/src/ 
```

And this time it should work, if you are on a mac you will need a patch to FDB so that you can
properly find msgpack

For the record I use this command line to generate the `build.ninja` file on a MacOS machine:
```
cmake ../src -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DOPENSSL_ROOT_DIR=$(brew --prefix openssl@3) -DBOOST_ROOT=$(brew --prefix boost@1.85)
```

My `fdb_bazel_support` branch has the import file that should work on MacOS and also a `MODULE` file
if you want to build things after the bazelfiication to checkt that everything still works

## Additional features

`ninja2bazel` supports remapping of paths/files and manually generated targets.

### Remapping paths/files

Initially this was developped to deal with symlinks to other folders outside of the what was currently bazelified, for instance your are trying to bazelify your C++ code that is in `cpp` but you have already bazelified your protobuf that is in `proto` and you have a symlink from `cpp/proto` to `../proto`, using `--remap cpp/proto=proto` would allow to use targets that would be defined in the proto folder.

More recently this feature was extended to remap files as well, in this case you don't specify the full path where you want it remap but just the prefix to remap to; for instance if you have a file that is generated during the build you can remap it to a pre-exiting file that you have placed somewhere else, you would use `--remap flow/config.h=bazel/build` will remap the file flow/config.h to bazel/build assuming that there is a file called `flow/config.h` there.
The tool will take care of setting the `include` value properly to make things work.

### Manually generated targets
Sometime the build generates files but they are not generated by `ninja` a counter example for that are files generated by `cmake` because it won't work for them because usually the CMake build don't include them in the dependencies they are more often than not just included headers. In that case it's better to use the pregenerated support for that but for instance `RocksDB` build generates a file and add it as dependency to other targets but don't generate the command to get the generate the file itself. In this case you want to use `-m foo/bar.h=bazel/build/bar.h`.
Beware that in order for this to work today you need to use a different prefix, this will need to be changed in the future to be more flexible.
