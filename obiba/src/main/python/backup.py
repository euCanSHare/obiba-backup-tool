#!/usr/bin/env python

####################################################################################################################
# 'backup.py' is a simple script used to backup Obiba products on a server.
#
# For each project, files, folders and databases (MySQL and MongoDB) are backed up as specified in the backup.conf. 
# Backups are stored in date structured directory (e.g. destination/project/year/month/day&time/)
# A clean up schedule deletes old backups as specified in the backup.conf
# The current local backup is copied to a remote backup location
# Additional folders may also be copied to the remote  backup location
#
####################################################################################################################

import os
from datetime import datetime
from datetime import date
import subprocess
import gzip
from subprocess import call
import shutil
import traceback
import yaml
import glob
import shlex

class ObibaBackup:
    CONFIG_FILE = os.path.join(os.path.dirname(__file__), "backup.conf")

    def run(self):
        """
        This is where everything starts
        """
        try:
            print "# Obiba backup started (%s)" % datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.__loadConfig()
            self.__setup()
            self.__backupRemoteProjects()
            self.__backupProjects()
        except Exception, e:
            print '*' * 80
            print "* ERROR"
            print
            print traceback.format_exc()
            print '*' * 80
        finally:
            print "# Obiba backup completed (%s)" % datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    ####################################################################################################################
    # P R I V A T E     M E T H O D S
    ####################################################################################################################

    def __loadConfig(self):
        configFile = open(self.CONFIG_FILE, 'r')
        self.config = yaml.load(configFile)
        configFile.close()

    ####################################################################################################################
    def __setup(self):
        """
        Setup basically creates the daily backup folder for each project
        """

        backupFolder = self.config['destination']
        self.__createBackupFolder(backupFolder)

        # create the project based backup folder
        today = date.today()

        if 'projects' in self.config:
            for project in self.config['projects'].iterkeys():
                timestamp = datetime.now().strftime('%d-%H-%M-%S')
                backupDestination = os.path.join(backupFolder, project, str(today.year), today.strftime('%m'), timestamp)
                self.__createBackupFolder(backupDestination)
                self.config['projects'][project]['destination'] = backupDestination

    ####################################################################################################################
    def __backupRemoteProjects(self):
        if 'rsyncs' in self.config:
            for rsync in self.config['rsyncs']:
                if 'folder' in rsync:
                    self.__backupToRemoteServer(rsync['folder'])

    ####################################################################################################################
    def __backupProjects(self):
        if 'projects' in self.config:
            for project in self.config['projects'].iterkeys():
                print "Backing up %s..." % project
                self.__backupProject(self.config['projects'][project], project)

    ####################################################################################################################
    def __backupProject(self, project, projectName):
        destination = project['destination']
        self.__cleanup(os.path.dirname(destination), projectName)
        if 'files' in project:
            self.__backupFiles(project['files'], destination)
        if 'folders' in project:
            self.__backupFolders(project['folders'], destination)
        if 'mongodbs' in project:
            self.__backupMongodbs(project['mongodbs'], destination)
        if 'databases' in project:
            self.__backupDatabases(project['databases'], destination)

        source = {}
        source['path'] = destination
        self.__backupToRemoteServer(source, projectName)

    ####################################################################################################################
    def __backupToRemoteServer(self, source, remote=None):
        if 'rsync' in self.config and 'destination' in self.config['rsync']:
            excludes = []
            if 'excludes' in source:
                for exclude in source['excludes']:
                    excludes.append('--exclude')
                    excludes.append('%s' % exclude)

            folder = remote if remote else os.path.basename(source['path'])
            source = os.path.join(source['path'], '')
            destination = "%s/%s" % (self.config['rsync']['destination'], folder)
            publicKey = ''

            if 'pem' in self.config['rsync']:
                publicKey = "ssh -i %s" % self.config['rsync']['pem']

            print "Backing up %s to remote server %s..." % (source, self.config['rsync']['destination'])
            print "rsync -Atrave '%s' %s %s %s" % (publicKey, ' '.join(str(x) for x in excludes), source, destination)
            result = subprocess.check_output(
              [
                  'rsync',
                  '-Atrave',
                  publicKey,
                  source,
                  destination
              ] + excludes
            )

            print result

    ####################################################################################################################
    def __cleanup(self, destination, project):
        month = self.config['keep']['month']
        days = self.config['keep']['days']
        if 'keep' in self.config['projects'][project]:
            if 'month' in self.config['projects'][project]['keep']:
                month = self.config['projects'][project]['keep']['month']
            if 'days' in self.config['projects'][project]['keep']:
                days = self.config['projects'][project]['keep']['days']
        self.__cleanupFolders(os.path.dirname(destination), month)
        self.__cleanupFolders(destination, days)

    ####################################################################################################################
    def __cleanupFolders(self, destination, keep):
        sortedFolders = self.__getSortedFolderList(destination)
        self.__deleteFolders(len(sortedFolders) - keep, destination, sortedFolders)

    ####################################################################################################################
    def __backupFiles(self, files, destination):
        for file in files:
            print "\tBacking up file %s to %s" % (file, destination)
            for fileItem in glob.glob(file):
                if os.path.isfile(fileItem):
                  destinationPath = os.path.join(destination, os.path.dirname(fileItem)[1:])
                  if not os.path.exists(destinationPath):
                    os.makedirs(destinationPath)
                  shutil.copy(fileItem, destinationPath)

    ####################################################################################################################
    def __backupFolders(self, folders, destination):
        for folder_item in folders:
            excludes = []
            if 'folder' in folder_item:
                #Using hierarchical folder structure 
                if 'path' in folder_item:
                    folder_path = folder_item['path']
                    
                    if 'excludes' in folder_item:
                        for exclude in folder_item['excludes']:
                            if not (os.path.exists(exclude) or os.path.exists(os.path.join(folder_path,exclude))):
                                print "\tExclude path %s not found, check the config entry is correct" % exclude 
                            excludes.append('--exclude=%s' % exclude)
            else:
                #Using simple folder list
                folder_path = folder_item
                
            print "\tBacking up folder %s to %s" % (folder_path, destination)
            filename = "%s.tar.gz" % (os.path.basename(folder_path))
                            
            destinationPath = os.path.join(destination, folder_path[1:])
            if not os.path.exists(destinationPath):
              os.makedirs(destinationPath)
            backupFile = os.path.join(destinationPath, filename)
            #print ' '.join(str(x) for x in ["tar", "czfP", backupFile, folder_path] + excludes)
            #result = call(["tar", "czfP", backupFile, folder_path] + excludes) # ORIGINAL
            result = call(["tar", "czfP", backupFile] + excludes + [folder_path])


            if result != 0:
                print "Failed to tar %s" % backupFile
                        
    ####################################################################################################################
    def __backupMongodbs(self, mongodbs, destination):
        #Build the mongodump command based on the config. Config file struture assumes settings are the same for all databases
        mongocommand = 'mongodump --host ' + str(mongodbs['host']) + ' --port ' +  str(mongodbs['port']) + ' '
        if 'usr' in mongodbs and 'pwd' in mongodbs:
            mongocommand += '--username ' + str(mongodbs['usr']) + ' --password ' +  str(mongodbs['pwd']) + ' '
        if 'authenticationDatabase' in mongodbs:
            mongocommand += '--authenticationDatabase ' + str(mongodbs['authenticationDatabase']) + ' '
        if 'sslPEMKeyFile' in mongodbs:
            mongocommand += '--ssl --sslPEMKeyFile ' + str(mongodbs['sslPEMKeyFile']) + ' '
        output_type = '--archive=' if ('output' in mongodbs and 'archive' == mongodbs['output']) else '--out='
        output_type += destination
        #Run command for each database in the config file
        for mongodb in mongodbs['names']:
            print "\tBacking up mongodb %s to %s" % (mongodb, destination)
            self.__backupMongodb(mongodb, mongocommand, output_type)

    ####################################################################################################################
    def __backupMongodb(self, mongodb, mongocommand, output_type):
        #Complete the database specific commands
        if output_type[:9] == "--archive":
            output_type += os.sep + mongodb + '.tar.gz '
        else:
            output_type += os.sep + mongodb + ' '
        mongocommand += output_type + ' --gzip ' + ' --db ' + mongodb + ' '
        #Convert command string to list
        safe_args = shlex.split(mongocommand)
        #Execute os command
        subprocess.check_output(safe_args)

    ####################################################################################################################
    def __backupDatabases(self, databases, destination):
        if 'prefix' in databases:
            names = self.__listDatabases(databases['prefix'], databases['usr'], databases['pwd'])
        else:
            names = databases['names']

        for database in names:
            self.__backupDatabase(database, destination, databases['usr'], databases['pwd'])

    ####################################################################################################################
    def __listDatabases(self, prefix, usr, pwd):
        matchingCommand = "SHOW DATABASES LIKE '" + prefix + "'"
        listCommand = ["mysql", "-u", usr, "-p" + pwd, "-B", "-N", "-e", matchingCommand]
        listProcess = subprocess.Popen(listCommand, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        listOutput = listProcess.communicate()[0]
        return listOutput.rstrip().split('\n')

    ####################################################################################################################
    def __backupDatabase(self, database, destination, usr, pwd):
        print "\tBacking up database %s to %s" % (database, destination)
        filename = "%s.sql.gz" % (os.path.basename(database))
        backupFile = os.path.join(destination, filename)

        dumpCommand = ["mysqldump", "-u", usr, "-p" + pwd, database]
        dumpProcess = subprocess.Popen(dumpCommand, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        dumpOutput = dumpProcess.communicate()[0]

        zipFile = gzip.open(backupFile, "wb")
        zipFile.write(dumpOutput)
        zipFile.close()

    ####################################################################################################################
    def __deleteFolders(self, deleteCount, destination, sortedFolders):
        if deleteCount > 0:
            foldersToDelete = sortedFolders[:deleteCount]
            for folder in foldersToDelete:
                print "\tDeleting %s" % os.path.join(destination, folder[0])
                shutil.rmtree(os.path.join(destination, folder[0]))

    ####################################################################################################################
    def __getSortedFolderList(self, destination):
        files = os.listdir(destination)
        file_date_tuple_list = [(x, os.path.getmtime(os.path.join(destination, x))) for x in files]
        file_date_tuple_list.sort(key=lambda x: x[1])
        return file_date_tuple_list

    ####################################################################################################################
    def __createBackupFolder(self, path):
        if not os.path.exists(path):
            os.makedirs(path)

####################################################################################################################
# S C R I P T    M A I N    E N T R Y
####################################################################################################################

if __name__ == "__main__":
    ObibaBackup().run()
