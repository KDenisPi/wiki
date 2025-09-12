/**
 * @file item_reader.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief Read WiKi Item information from file and TODO
 * @version 0.1
 * @date 2025-08-13
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_ITEM_READER_H_
#define WIKI_ITEM_READER_H_

#include <string>
#include <ostream>
#include <iostream>

#include "defines.h"

namespace wiki {

class ItemReader{
public:
    ItemReader() {}

    /**
     * @brief Destroy the Item Reader object
     *
     */
    ~ItemReader() {
        close();
    }

    /**
     * @brief
     *
     * @param filename
     * @return true
     * @return false
     */
    bool init(const std::string filename){
        fp_prop = fopen(filename.c_str(), "r");
        // Check if the file was opened successfully
        if (fp_prop == NULL) {
            std::cout << "Error reading file " << filename << " Error: " << errno << std::endl; // Print an error message
            return false;
        }

        return true;
    }

    /**
     * @brief Get the next Item line from the file
     *
     * @param buff
     * @param buff_size
     * @return true
     * @return false
     */
    bool next(char* buff, size_t buff_size){
        if(fgets(buff, buff_size, fp_prop) != NULL) {
            return true;
        }

        return false;
    }

    /**
     * @brief
     *
     */
    void close(){
        if(fp_prop != nullptr){
            fclose(fp_prop);
            fp_prop = nullptr;
        }
    }

    const bool is_ready() const{
        return (fp_prop != nullptr);
    }

private:
    std::string items_file;
    FILE *fp_prop = nullptr;
    fpos_t pos;
    bool loaded = false;
};

} //namespace
#endif