#!/usr/bin/env python
# This file is part of VoltDB.
# Copyright (C) 2008-2017 VoltDB Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with VoltDB.  If not, see <http://www.gnu.org/licenses/>.
import os, sys, subprocess
import argparse
import re
import multiprocessing

########################################################################
#
# Make the command line parser.
#
########################################################################
def makeParser():
    parser = argparse.ArgumentParser(description='Build VoltDB EE Engine.')
    #
    # Build configuration.
    #
    parser.add_argument('--debug',
                        action='store_true',
                        help='''
                        Print commands for debugging.  Don't execute anything.
                        ''')
    parser.add_argument('--build-type',
                        dest='buildtype',
                        default='release',
                        help='''
                        VoltDB build type.  One of debug, release, memcheck, memcheck_nofreelist.
                        The default is release.''')
    parser.add_argument('--profile',
                        action='store_true',
                        help='''
                        Configure for profiling.''')
    parser.add_argument('--coverage',
                        action='store_true',
                        help='''
                        Configure for coverage testing.''')
    parser.add_argument('--generator',
                        default='Unix Makefiles',
                        help='''
                        Name the tool used to do builds.  Currently only 'Unix Makefiles' is supported,
                        and this is the default.  The other choices are 'Ninja', 'Eclipse CDT4 - Unix Makefiles'
                        and 'Eclipse CDT4 - Ninja'.  These choose the ninja build system, and will also
                        create an Eclipse CDT4 project in the build area.''')
    parser.add_argument('--show-test-output',
                        action='store_true',
                        dest='showtestoutput',
                        default=False,
                        help='''
                        By default tests are run with test output shown only for failing tests.
                        If this option is included then all test output will be shown, even if
                        the tests pass.
                        ''')
    #
    # Build parameters.
    #
    parser.add_argument('--source-directory',
                        dest='srcdir',
                        metavar='SOURCE_DIR',
                        required=True,
                        help='''
                        Root of VoltDB EE source tree.
                        This is required.
                        ''')
    parser.add_argument('--test-directory',
                        dest='testdir',
                        required=True,
                        metavar='TESTDIR',
                        help='''
                        Root of the VoltDB test source tree.
                        This is required.
                        ''')
    parser.add_argument('--object-directory',
                        dest='objdir',
                        required=True,
                        metavar='OBJECT_DIR',
                        help='''
                        Root of the object directory.  This is typically S/obj/BT,
                        where S is the source directory for all of VoltDB and BT
                        is the build type.  This is required.
                        ''')
    parser.add_argument('--max-processors',
                        dest='max_processors',
                        default=-1,
                        help='''
                        Specify the maximum number of processors.  By default we use
                        all cores, and we will never use more than the number of cores.
                        But if this number is less than the number of cores we will
                        use this number.  If this number is not specified and we cannot
                        determine the number of cores we will use 1.
                        ''')
    ####################################################################
    #
    # Build Steps.
    #
    # The steps are:
    #   1.) --clean
    #       Do a clean before doing anything else.  This deletes the
    #       entire object directory.
    #   2.) Building artifacts.
    #       2a.) --build
    #           Build the VoltDB shared object.  This builds all the dependences,
    #           compiles all the files and links them into a shared library.
    #       2b.) --build-ipc
    #           Build the VoltDB IPC executable.  This builds all the dependences,
    #           compiles all the files and links them along with the result of
    #           compiling the ipc sources.  This implies --build as well, so the
    #           shared object will be linked.
    #   2.) --install
    #       Install the VoltDB shared object and the voltipc excutable if
    #       the latter exists.
    #   4.) Building Tests
    #       4a.) --build-one-test=test or --build-one-testdir=testdir
    #           Build one EE unit test or else build all the tests in a given
    #           test directory.
    #       4b.) --build-tests
    #           This builds all the tests.
    #   5.) Running Tests
    #       5a.) --run-one-test=test or --run-one-testdir=testdir
    #            Run one test or all the tests in the given test directory.
    #       5b.) --run-all-tests
    #           This runs all the tests.  The tests are run concurrently.  The
    #           only output shown is failing output unless --show-test-output has
    #           been specified.  Note that this will run valgrind as well if
    #           the build type is memcheck.
    #
    ####################################################################
    parser.add_argument('--clean',
                        dest='cleanbuild',
                        action='store_true',
                        help='''
                        Do a completely clean build by deleting the obj directory first.''')
    parser.add_argument('--build',
                        action='store_true',
                        help='''
                        Just build the EE jni library.''')
    parser.add_argument('--build-ipc',
                        dest='buildipc',
                        action='store_true',
                        help='''
                        Just build the EE IPC jni library (used for debugging).''')
    parser.add_argument('--build-all-tests',
                        dest='buildalltests',
                        action='store_true',
                        help='''
                        Just build the EE unit tests.  Do not run them.  This implies --build.
                        This is incompatible with --build-one-test and --build-one-testdir.
                        ''')
    parser.add_argument('--build-one-test',
                        dest='buildonetest',
                        metavar='TEST',
                        help='''
                        Build only one EE unit test.  This is incompatible with
                        --build-all-tests and build-one-testdir.  This implies
                        --build.
                        ''')
    parser.add_argument('--build-one-testdir',
                        dest='buildonetestdir',
                        metavar='TESTDIR',
                        help='''
                        Build all tests in TESTDIR.  This is incompatible with
                        --build-all-tests and --build-one-test.  This implies
                        --build.
                        ''')
    #
    # Installation
    #
    parser.add_argument('--install',
                        action='store_true',
                        help='''
                        Install the binaries''')
    #
    # Testing.
    #
    parser.add_argument('--run-all-tests',
                        dest='runalltests',
                        action='store_true',
                        help='''
                        Build and run the EE unit tests.  Use valgrind for
                        memcheck or memcheck_nofreelist.
                        This implies --build-all-tests. This is mutually
                        incompatible with --run-one-test and --run-one-testdir.  This
                        implies --build-all-tests.
                        ''')
    parser.add_argument('--run-one-test',
                        dest='runonetest',
                        metavar='TEST',
                        help='''
                        Run one test.  This is mutually incompatible with --run-all-tests
                        and --run-one-testdir.  This implies --build-one-test=TEST.
                        ''')
    parser.add_argument('--run-one-testdir',
                        dest='runonetestdir',
                        metavar='TESTDIR',
                        help='''
                        Run all tests in TESTDIR.  This is
                        mutually incompatible with --run-all-tests and --run-one-test.
                        This implies --build-one-testdir=TESTDIR.
                        ''')
    return parser

########################################################################
#
# Delete a directory.  On failure exit with a non-zero status.
#
########################################################################
def deleteDirectory(dirname, config):
    if config.debug:
        print("Deleting directory %s" % dirname)
    else:
        subprocess.call('rm -rf %s' % dirname, shell=True)

########################################################################
#
# Get the number of cores we will use.  This is the min of
# the number of cores actually available and the number of
# cores specified in the parameters.  If none are specified
# in the parameters we use all available. If we cannot
# determine how many are available we use 1.
#
########################################################################
def getNumberProcessors(config):
    # np is the number of cores to use.
    np = multiprocessing.cpu_count()
    if np < 1:
        np = 1
        if 0 < config.max_processors:
            # We can't find out (np < 1) but the user has
            # given us a number (0 < config.max_processors).
            # Use the user's number.
            np = config.max_processors
    elif 1 <= config.max_processors and config.max_processors < np:
        # If we have a core count but the user gave us one
        # which is smaller then use the user's number.
        np = config.max_processors
    return np

########################################################################
#
# Make a string we can use to call the builder, which would
# be make or ninja.
#
########################################################################
def makeBuilderCall(config):
    np = getNumberProcessors(config)
    if config.generator.endswith('Unix Makefiles'):
        return "make -j%d " % np
    elif config.generator.endswith('Ninja'):
        return "ninja -j %d " % np
    else:
        print('Unknown generator \'%s\'' % config.generator)

########################################################################
#
# Get the cmake command string.
#
########################################################################
def configureCommandString(config):
    profile = "OFF"
    coverage = "OFF"
    if config.coverage:
        coverage = "ON"
    if config.profile:
        profile = 'ON'
    if config.buildtype == 'debug' or config.buildtype == 'memcheck':
        cmakeBuildType="Debug"
    else:
        cmakeBuildType="Release"
    return 'cmake -DCMAKE_BUILD_TYPE=%s -DVOLTDB_BUILD_TYPE=%s -G \'%s\' -DVOLTDB_USE_COVERAGE=%s -DVOLTDB_USE_PROFILING=%s %s' \
             % (cmakeBuildType, config.buildtype, config.generator, coverage, profile, config.srcdir)

########################################################################
#
# Build the builder string.  This would the call to make or
# ninja to build the tool.  Since both are so similar we use
# the same target specification.
#
# Note that we will have called validateConfig, which set
# some target implications.  For example, run-all-tests implies
# build-all-tests.
#
########################################################################
def buildCommandString(config):
    target=''
    cmdstr = None
    if config.build:
        target += ' build'
    if config.buildipc:
        target += ' buildipc'
    if config.install:
        target += ' install'
    if config.installipc:
        target += ' installipc'
    if config.buildonetest:
        target += " build-test-%s" % config.buildonetest
    elif config.buildonetestdir:
        target += " build-testdir-%s" % config.buildonetestdir
    elif config.buildalltests:
        target += " build-all-tests"
    if config.runonetest:
        target += ' run-test-%s' % config.runonetest
    elif config.runonetestdir:
        target += ' run-dir-%s' % config.runonetestdir
    elif config.runalltests:
        target += ' run-all-tests'
    # If we got no targets here then
    # don't return a string.  Return None.
    if len(target) > 0:
        cmdstr = "%s %s" % (makeBuilderCall(config), target)
    return cmdstr

def runCommand(commandStr, config):
    if config.debug:
        print(commandStr)
        return True
    else:
        retcode = subprocess.call(commandStr, shell = True)
        return (retcode == 0)


def morethanoneof(a, b, c):
    if a:
        return b or c
    elif b:
        return c
    else:
        return False

def validateConfig(config):
    # The config needs some variables
    # which are not defined but implied by
    # the command line parameters.
    config.installipc=False

    # Some of the build and run parameters are incompatible.
    if morethanoneof(config.runalltests, config.runonetest, config.runonetestdir):
        print("--run-all-tests, --run-one-testdir and --run-one-test are incompatible.")
        os.exit(1)
    if morethanoneof(config.buildalltests, config.buildonetest, config.buildonetestdir):
        print("--build-all-tests, --build-one-testdir and --build-one-test are incompatible")
        os.exit(1)
    # If we have specifed running something then we need
    # to build it.
    if config.runalltests or config.runonetest or config.runonetestdir:
        config.build = True
        config.install = True
        config.buildalltests = config.runalltests
        config.buildonetest = config.runonetest
        config.buildonetestdir = config.runonetestdir
    # If we ahve specified building one or more tests
    # then we need to build the shared library and install
    # it.
    if config.buildalltests or config.buildonetest or config.buildonetestdir:
        config.build = True
        config.install = True
    if config.buildipc:
        config.build = True
    if config.install:
        config.build = True
        if config.buildipc:
            config.installipc = True

def doCleanBuild(config):
    #
    # The config.objdir must either not exist or else
    # be a directory.  If this is a clean build we
    # delete the existing directory.
    #
    if os.path.exists(config.objdir) and not os.path.isdir(config.objdir):
        print('build.py: \'%s\' exists but is not a directory.' % config.objdir)
        sys.exit(100)
    deleteDirectory(config.objdir, config)

def ensureInObjDir(config):
    if not os.path.exists(config.objdir):
        if (config.debug):
            print("Making directory \"%s\"" % config.objdir)
        else:
            try:
                os.makedirs(config.objdir)
            except OSError as ex:
                print("Cannot make directory \"%s\": %s" % (config.objdir, ex))
                os.exit(1)
    if config.debug:
        print('Changing to directory %s' % config.objdir)
    else:
        try:
            os.chdir(config.objdir)
        except OSError as ex:
            print("Cannot change directory to \"%s\"", config.objdir)
            os.exit(1)

def doConfigure(config):
    #
    # If we have not already configured, we want to reconfigure.
    # We always want to do this.
    #
    configCmd = configureCommandString(config)
    if not runCommand(configCmd, config):
        print("Cmake command \"%s\" failed." % configCmd)
        sys.exit(100)

def doBuild(config):
    buildCmd = buildCommandString(config)
    if buildCmd:
        if not runCommand(buildCmd, config):
            print("Build command \"%s\" failed." % buildCmd)
            sys.exit(100)

def main():
    parser=makeParser()
    config=parser.parse_args()

    # Not all configs are valid.  Check here.
    validateConfig(config)

    # Are we doing a clean build?
    if config.cleanbuild:
        doCleanBuild(config)

    # Make sure we are in the obj directory.
    ensureInObjDir(config)

    # Configure the build if necessary.
    doConfigure(config)
    #
    # Do the actual build.  This will build the
    # shared library, the ipc executable and all tests
    # that are asked for.  This will also run all
    # the tests that are asked for.
    #
    doBuild(config)
    print("Build success.")

if __name__ == '__main__':
    main()
    sys.exit(0)
