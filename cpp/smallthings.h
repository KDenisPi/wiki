/*
 * smallthings.h
 *
 *  Small utilites
 *
 *  Created on: Jun 19, 2018
 *      Author: Denis Kudia
 */

#ifndef SMALLTHINGS_H_
#define SMALLTHINGS_H_

#include <chrono>
#include <ctime>
#include <string>
#include <unistd.h>
#include <dirent.h>
#include <sys/mman.h>
#include <fcntl.h>

namespace piutils {

/*
* Get current time on UTC or local
*/
void get_time(std::tm& result, std::time_t& time_now,const bool local_time = false);

/**
 * @brief Check if file exist and available
 *
 * @param fname
 * @param file_only - true check if path is regular file
 * @return true
 * @return false
 */
bool chkfile(const std::string& fname, const bool file_only = false);

/**
 * @brief If the file is regular file
 *
 * @param fname
 * @return true
 * @return false
 */
bool is_regular_file(const std::string& fname);

/*
* Return time string with format 'Mon, 29 Aug 2018 16:00:00 +1100'
* Used for email
*/
const std::string get_time_string(const bool local_time = true);

/*
*  Return list of files for directory
*  Size of list can be restricted by buffer size
*/
int get_dir_content(const std::string& dirname, std::string& result, const int max_result_size);

/*
* Trim spaces and CR LF
*/
const std::string trim(std::string& str);

}//namespace piutils
#endif
