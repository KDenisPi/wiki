/**
 * @file defines.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-12
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_DEFINES_H_
#define WIKI_DEFINES_H_

#include <tuple>
#include <string>
#include <memory>
#include <vector>

namespace wiki{

#define MAX_LINE_LENGTH 1024*1024*5
#define MAX_PARSING_THREADS 9 //5

using pID = std::string;

/**
 * @brief Property information
 * property ID, label, description
 *
 */
using pInfo = std::tuple<pID, std::string, std::string>;
using item_info = std::tuple<std::string, std::vector<std::string>>;

using dict_key = std::string;
using dict_val = std::vector<std::string>; //std::tuple<std::string, std::string>;

using prop_ids = std::vector<std::string>;

}

#endif
