/**
 * @file prop_dict.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-12
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <fstream>
#include <fcntl.h>
#include <unistd.h>

#include "prop_dict.h"

namespace wiki {

/**
 * @brief
 *
 * @param filename
 * @param target
 * @return const int
 */
int Properties::load_selection(const std::string& filename, std::unordered_set<pID>& target){
    if(filename.empty()){
        return 0;
    }

    std::ifstream inputFile(filename);
    if(!inputFile.is_open()){
        std::cerr << "Could not open selection file: " << filename << std::endl;
        return -1;
    }

    //a selection file replaces the built-in list, it does not extend it
    target.clear();

    int count = 0;
    std::string line;
    while(std::getline(inputFile, line)){
        //drop a trailing CR left by files edited on Windows
        if(!line.empty() && line.back() == '\r'){
            line.pop_back();
        }

        if(line.empty() || line[0] == '#'){
            continue;
        }

        const auto off = line.find(';');
        const std::string id = (off == std::string::npos ? line : line.substr(0, off));
        if(id.empty()){
            continue;
        }

        target.insert(id);
        count++;
    }

    inputFile.close();
    return count;
}

/**
 * @brief
 *
 * @param filename
 * @return true
 * @return false
 */
bool Properties::load(const std::string& filename){
    int fd_prop = open(filename.c_str(), O_RDONLY);
    if(fd_prop == -1){
        std::cout << "Error opening file " << filename << " Error: " << errno << std::endl; // Print an error message
        return false;
    }

    size_t b_read = b_read = read(fd_prop, buffer.get(), MAX_LINE_LENGTH-1);
    if(b_read == -1){
        std::cout << "Error reading file " << filename << " Error: " << errno << std::endl; // Print an error message
    }
    else{
        buffer.get()[b_read] = 0x00;

        ptr_prop->Parse(buffer.get());
        if(ptr_prop->HasParseError()){
            auto err = ptr_prop->GetParseError();
            std::cout << filename << " Parse error: " << std::to_string(err) << " Offset: " << ptr_prop->GetErrorOffset() << std::endl;
        }
        else{
            loaded = true;
        }
    }

    close(fd_prop);
    return loaded;
}

/**
 * @brief
 *
 * @param prop_id
 * @return const p_info
 */
const pInfo Properties::get_prop(const pID& prop_id) const{
    if(is_loaded()){
        auto prop = ptr_prop->FindMember(prop_id.c_str());
        if(ptr_prop->MemberEnd() != prop){
            return pInfo(prop_id, std::string(prop->value[0].GetString()), std::string(prop->value[1].GetString()));
        }
    }

    return pInfo(pID(), std::string(), std::string());
}

} //namespace